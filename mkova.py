#!/usr/bin/env python3

import argparse
import os
import struct
import tarfile
import tempfile
import xml.dom.minidom

from collections import Counter
from io import BytesIO
from math import ceil
from random import randint
from uuid import uuid1
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, tostring
import zlib

NS_CIM = "{http://schemas.dmtf.org/wbem/wscim/1/common}"
NS_OVF = "{http://schemas.dmtf.org/ovf/envelope/1}"
NS_RASD = "{http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData}"
NS_VMW = "{http://www.vmware.com/schema/ovf}"
NS_VSSD = "{http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData}"
NS_XSI = "{http://www.w3.org/2001/XMLSchema-instance}"

# VMDK part
SECTOR_SIZE = 512

MARKER_EOS      = 0 # end of stream
MARKER_GT       = 1 # grain table
MARKER_GD       = 2 # grain directory
MARKER_FOOTER   = 3 # footer

# Descriptor Template
IMAGE_DESCRIPTOR_TEMPLATE ='''# Disk Descriptor File
version=1
CID=#CID#
parentCID=ffffffff
createType="streamOptimized"

# Extent description
RDONLY #SECTORS# SPARSE "stream-optimized.vmdk"

# The Disk Data Base
#DDB

ddb.adapterType = "ide"
# #SECTORS# / 63 / 255
ddb.geometry.cylinders = "#CYLINDERS#"
ddb.geometry.heads = "255"
ddb.geometry.sectors = "63"
ddb.longContentID = "#longCID#"
ddb.virtualHWVersion = "7"'''

def pad_to_sector(b):
    """
    take bytes and pad them to sector-size boundary with zeroes
    """
    l = len(b)
    sectors = ceil(l/SECTOR_SIZE)
    padding = sectors * SECTOR_SIZE - l
    if padding:
        return b + b'\x00' * padding
    else:
        return b

def create_marker(marker_type, sectors, size):
    """
    Create sector-sized stream-optimized VMDK marker
    """
    marker_list = [ sectors, size, marker_type ]
    marker_list += [0,] * 496
    return struct.pack("=QII496B", *marker_list)

def stream_optimize_vmdk(inf, outf, newsize):
    """
    Convert monolithSparse VMDK file object inf to stream-optimized
    VMDK file object outf and resize it to newsize gigabytes
    """

    header_struct = "=IIIQQQQIQQQBccccH433B"
    sparse_header = inf.read(SECTOR_SIZE)
    fields = struct.unpack(header_struct, sparse_header)
    magicNumber, version, flags, capacity, grainSize, descriptorOffset, \
        descriptorSize, numGTEsPerGT, rgdOffset, gdOffset, overHead, \
        uncleanShutdown, singleEndLineChar, nonEndLineChar, doubleEndLineChar1, \
        doubleEndLineChar2, compressAlgorithm  = fields[:-433]


    sectors = capacity

    # Override some header values
    version = 3
    rgdOffset = 0
    flags = 0x30001
    compressAlgorithm = 1 # deflate
    capacity = ceil(newsize*1024*1024*1024/SECTOR_SIZE)
    # Round up to GT size
    sectorsInGT = grainSize * numGTEsPerGT
    newGTs = ceil(capacity/sectorsInGT)
    capacity = newGTs * sectorsInGT
    new_header_fields = [ magicNumber, version, flags, capacity,
                grainSize, descriptorOffset, descriptorSize, numGTEsPerGT,
                rgdOffset, gdOffset, overHead, uncleanShutdown,
                b'\n', b' ', b'\r', b'\n', compressAlgorithm ]

    totalGrains = ceil(sectors/grainSize)
    totalGTs = ceil(totalGrains/numGTEsPerGT)

    inf.seek(gdOffset * SECTOR_SIZE)

    # Load all GTEs in a flat array
    gd = inf.read(totalGTs * 4)
    gdes = struct.unpack(f'={totalGTs}I', gd)
    gts = []

    for gt_offset in gdes:
        inf.seek(gt_offset * SECTOR_SIZE)
        gt = inf.read(numGTEsPerGT * 4)
        gtes = list(struct.unpack(f'={numGTEsPerGT}I', gt))
        gts.append(gtes)

    # Prepare new image descriptor
    cid = '%08x' %  randint(1, 0xffffffff)
    longcid = str(uuid1()).replace('-', '')
    cylinders = ((capacity + (63*255) - 1) / (63*255))
    image_descriptor_str = IMAGE_DESCRIPTOR_TEMPLATE
    image_descriptor_str = image_descriptor_str.replace("#CID#", cid)
    image_descriptor_str = image_descriptor_str.replace("#longCID#", longcid)
    image_descriptor_str = image_descriptor_str.replace("#SECTORS#", str(capacity))
    image_descriptor_str = image_descriptor_str.replace("#CYLINDERS#", str(cylinders))
    image_descriptor = pad_to_sector(image_descriptor_str.encode('ascii'))

    new_header_fields += [0] * 433
    sparse_header = struct.pack(header_struct, *new_header_fields)

    # Write sparse header, image descriptor
    # and pad with zeroes up to overHead sectors
    outf.write(sparse_header)
    outf.write(image_descriptor)
    padlen = overHead * SECTOR_SIZE - outf.tell()
    if padlen > 0:
        outf.write(b'\x00' * padlen)

    newGrainDirectory = []

    # prepare stock GrainTable with all zeroes for fast comparisons
    emptyGT = [0] * numGTEsPerGT

    # current grain data offset in what would be non-sparse image file
    inPtr = 0

    # Go over all GrainTable  in GrainDirectory
    for gt in gts:
        # If GTi is all zeroes, no need to write anything
        # mark it as 0-offset in GrainDirectory
        if gt == emptyGT:
            newGrainDirectory.append(0)
            # Skip pointer for the amount covered by single GrainTable
            inPtr += numGTEsPerGT * grainSize
            continue

        # Go over all GrainTable entries and modify grain offsets
        # to make it GrainTable for output data. The size of GT in
        # infile and outfile is the same so it's OK to re-use original
        # table
        for i in range(len(gt)):
            offset = gt[i]

            # zero-filled grain, use 0 as an offset and procede
            if offset <= 1:
                gt[i] = 0
                inPtr += grainSize
                continue

            # Read actual data from the sparse file
            inf.seek(offset * SECTOR_SIZE)
            grainData = inf.read(grainSize * SECTOR_SIZE)

            # compress
            compressedGrainData = zlib.compress(grainData)

            if outf.tell() % SECTOR_SIZE:
                raise Exception

            # get the offset (in sectors) of the grain in output file
            # and override current offset in the current GrainTable
            gt[i] = int(outf.tell() / SECTOR_SIZE)

            # Write grain marker (6 bytes) then compressed data, then
            # pad it to sector size
            marker = struct.pack("=QI", inPtr, len(compressedGrainData))
            padded = pad_to_sector(marker + compressedGrainData)
            outf.write(padded)

            # move the virtual input pointer
            inPtr += grainSize

        # Write current GrainTable
        if outf.tell() % SECTOR_SIZE:
            raise Exception
        # First GT marker with size
        gt_marker = create_marker(MARKER_GT, int(len(gt) * 4 / SECTOR_SIZE), 0)
        outf.write(gt_marker)

        # Get GTi offset (in sectors) in output file
        pos = outf.tell()
        if pos % SECTOR_SIZE:
            raise Exception
        pos = int(pos / SECTOR_SIZE)
        # Write GTi content
        outf.write(struct.pack(f'{numGTEsPerGT}I', *gt))

        # and add the GT offset to new GrainDirectory
        newGrainDirectory.append(pos)


    # add zeroed-out GrainTable-s to the new GrainDirectory
    # to reach the requested image size
    paddingGTs = newGTs - len(newGrainDirectory)
    if paddingGTs > 0:
        newGrainDirectory += [0] * paddingGTs

    # Pack the content of the GrainDirectory and pad to sector size
    gdEntries = len(newGrainDirectory)
    newGD = struct.pack(f'{gdEntries}I', *newGrainDirectory)
    newGD = pad_to_sector(newGD)

    # Write GD marker
    directory_marker = create_marker(MARKER_GD, int(len(newGD)/SECTOR_SIZE), 0)
    outf.write(directory_marker)

    # Get offset (in sectors) of the new GrainDirectory
    # in the output file
    pos = outf.tell()
    if pos % SECTOR_SIZE:
        raise Exception
    gdOffset = int(pos / SECTOR_SIZE)

    # Write new GrainDirectory data
    outf.write(newGD)

    outf.write(create_marker(MARKER_FOOTER, 1, 0))

    # Update the GrainDirectory location in the footer sparse header
    new_header_fields[9] = gdOffset
    sparse_header_footer = struct.pack(header_struct, *new_header_fields)
    outf.write(sparse_header_footer)

    # And done
    outf.write(create_marker(MARKER_EOS, 0, 0))
    outf.close()

class OVAFile(object):

    def __init__(self, vmdk, cpus=1, memsize=1024, disksize=10, name=None):
        self.__instance = 0
        self.__vmdk = vmdk
        self.__cpus = cpus
        self.__memsize = memsize
        self.__disksize = disksize
        basename = os.path.basename(vmdk)
        self.__vmdk_barename = os.path.splitext(basename)[0]
        if name is None:
            self.__name = self.__vmdk_barename
        else:
            self.__name = name

        ET.register_namespace("cim", "http://schemas.dmtf.org/wbem/wscim/1/common")
        ET.register_namespace("ovf", "http://schemas.dmtf.org/ovf/envelope/1")
        ET.register_namespace("rasd", "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData")
        ET.register_namespace("vmw", "http://www.vmware.com/schema/ovf")
        ET.register_namespace("vssd", "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData")
        ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")


    def __add_child(self, e, name, text):
        new_e = SubElement(e, name)
        new_e.text = text
        return new_e

    def __add_config(self, e, name, value, required=False):
        new_e = SubElement(e, NS_VMW + 'Config')
        if not required:
            new_e.set(NS_OVF + 'required', 'false')
            new_e.set(NS_VMW + 'key', name)
            new_e.set(NS_VMW + 'value', value)
        return new_e

    def __add_item(self, e, name, desc, resource_type=None, resource_subtype=None,
      units=None, quantity=None, address=None, automatic_allocation=None, parent=None,
      address_on_parent=None, host_resource=None):
        new_e = SubElement(e, 'Item')
        SubElement(new_e, NS_RASD + 'ElementName').text = name
        SubElement(new_e, NS_RASD + 'Description').text = desc
        SubElement(new_e, NS_RASD + 'InstanceID').text = str(self.__instance)
        if resource_type is not None:
            SubElement(new_e, NS_RASD + 'ResourceType').text = str(resource_type)
        if resource_subtype is not None:
            SubElement(new_e, NS_RASD + 'ResourceSubType').text = str(resource_subtype)
        if units is not None:
            SubElement(new_e, NS_RASD + 'AllocationUnits').text = str(units)
        if quantity is not None:
            SubElement(new_e, NS_RASD + 'VirtualQuantity').text = str(quantity)
        if address is not None:
            SubElement(new_e, NS_RASD + 'Address').text = str(address)
        if automatic_allocation is not None:
            SubElement(new_e, NS_RASD + 'AutomaticAllocation').text = str(automatic_allocation)
        if parent is not None:
            SubElement(new_e, NS_RASD + 'Parent').text = str(parent)
        if address_on_parent is not None:
            SubElement(new_e, NS_RASD + 'AddressOnParent').text = str(address_on_parent)
        if host_resource is not None:
            SubElement(new_e, NS_RASD + 'HostResource').text = str(host_resource)
        i = self.__instance
        self.__instance += 1
        return new_e, i

    def __add_network_section(self, envelope):
        network_section = SubElement(envelope, 'NetworkSection')
        self.__add_child(network_section, 'Info', 'The list of logical networks')
        network = SubElement(network_section, 'Network')
        network.set(NS_OVF + 'name', 'VM Network')
        self.__add_child(network, 'Description', 'The VM Network network')

    def __add_virtual_system(self, envelope):
        vs = SubElement(envelope, 'VirtualSystem')
        vs.set(NS_OVF + 'id', self.__name)
        self.__add_child(vs, 'Info', 'A virtual machine')
        self.__add_child(vs, 'Name', self.__name)

        oss = SubElement(vs, 'OperatingSystemSection')
        oss.set(NS_OVF + 'id', '78')
        oss.set(NS_VMW + 'osType', 'freebsd64Guest')
        SubElement(oss, 'Info').text = 'The kind of installed guest operating system'

        product = SubElement(vs, 'ProductSection')
        SubElement(product, 'Info').text = 'Information about the installed software'
        SubElement(product, 'Product').text = ''
        SubElement(product, 'Vendor').text = ''
        SubElement(product, 'Version').text = ''

        vhw = SubElement(vs, 'VirtualHardwareSection')
        SubElement(vhw, 'Info').text = 'Virtual hardware requirements'

        # Add system entry
        system = SubElement(vhw, 'System')
        SubElement(system, NS_VSSD + 'ElementName').text = 'Virtual Hardware Family'
        SubElement(system, NS_VSSD + 'InstanceID').text = str(self.__instance)
        SubElement(system, NS_VSSD + 'VirtualSystemIdentifier').text = self.__name
        # This is the VM format type
        SubElement(system, NS_VSSD + 'VirtualSystemType').text = 'vmx-08'
        self.__instance += 1

        i, _ = self.__add_item(vhw, f'{self.__cpus} virtual CPU(s)', 'Number of Virtual CPUs',
            resource_type=3, quantity=self.__cpus, units='hertz * 10^6')

        i, _ = self.__add_item(vhw, f'{self.__memsize}MB of memory', 'Memory Size',
            resource_type=4, quantity=self.__memsize, units='byte * 2^20')

        # Disable for now as it's not required
        # i, storage_controller_id = self.__add_item(vhw, 'SCSI Controller 0', 'SCSI Controller',
        #     resource_type=6, resource_subtype='lsilogic', address=0)
        # self.__add_config(i, "slotInfo.pciSlotNumber", "16")

        i, storage_controller_id = self.__add_item(vhw, 'ideController0', 'IDE Controller',
            resource_type=5, resource_subtype='PIIX4', address=0)

        i, _ = self.__add_item(vhw, 'ideController1', 'IDE Controller',
            resource_type=5, resource_subtype='PIIX4', address=0)

        i, _ = self.__add_item(vhw, 'VirtualVideoCard', 'Virtual Video Card',
            resource_type=24, automatic_allocation='false')
        i.set(NS_OVF + 'required', 'false')
        self.__add_config(i, "enable3DSupport", "false")
        self.__add_config(i, "enableMPTSupport", "false")
        self.__add_config(i, "use3dRenderer", "automatic")
        self.__add_config(i, "useAutoDetect", "false")
        self.__add_config(i, "videoRamSizeInKB", "4096")

        i, _ = self.__add_item(vhw, 'Hard Disk 1', 'Hard Disk',
            resource_type=17, parent=storage_controller_id, address_on_parent=0,
            host_resource='ovf:/disk/vmdisk1')
        self.__add_config(i, "backing.writeThrough", "false")

        i, _ = self.__add_item(vhw, 'Ethernet 1', 'VmxNet3 ethernet adapter on "VM Network"',
            resource_type=10, resource_subtype='VmxNet3', address_on_parent=7,
            automatic_allocation='true')

        self.__add_config(i, "slotInfo.pciSlotNumber", "160")
        self.__add_config(i, "wakeOnLanEnabled", "true")

        self.__add_config(vhw, "cpuHotAddEnabled", "false")
        self.__add_config(vhw, "cpuHotRemoveEnabled", "false")
        self.__add_config(vhw, "firmware", "bios")
        self.__add_config(vhw, "virtualICH7MPresent", "false")
        self.__add_config(vhw, "virtualSMCPresent", "false")
        self.__add_config(vhw, "memoryHotAddEnabled", "false")
        self.__add_config(vhw, "nestedHVEnabled", "false")
        self.__add_config(vhw, "powerOpInfo.powerOffType", "soft")
        self.__add_config(vhw, "powerOpInfo.resetType", "soft")
        self.__add_config(vhw, "powerOpInfo.standbyAction", "checkpoint")
        self.__add_config(vhw, "powerOpInfo.suspendType", "hard")
        self.__add_config(vhw, "tools.afterPowerOn", "true")
        self.__add_config(vhw, "tools.afterResume", "true")
        self.__add_config(vhw, "tools.beforeGuestShutdown", "true")
        self.__add_config(vhw, "tools.beforeGuestStandby", "true")
        self.__add_config(vhw, "tools.syncTimeWithHost", "false")
        self.__add_config(vhw, "tools.toolsUpgradePolicy", "manual")

    def __generate_ovf(self):
        envelope =  Element('Envelope')
        envelope.set('xmlns', 'http://schemas.dmtf.org/ovf/envelope/1')
        envelope.set(NS_VMW + 'buildId', 'build-2494585')
        references = SubElement(envelope, 'References')
        f = SubElement(references, 'File')
        f.set(NS_OVF + "href", self.__vmdk_barename + '-drive.vmdk')
        f.set(NS_OVF + "id", 'file1')
        f.set(NS_OVF + "size", str(os.path.getsize(self.__vmdk)))

        disk_section = SubElement(envelope, 'DiskSection')
        SubElement(disk_section, 'Info').text = 'Virtual disk information'
        disk = SubElement(disk_section, 'Disk')
        disk.set(NS_OVF + 'capacity', str(self.__disksize))
        disk.set(NS_OVF + 'capacityAllocationUnits', 'byte * 2^30')
        disk.set(NS_OVF + 'diskId', 'vmdisk1')
        disk.set(NS_OVF + 'fileRef', 'file1')
        disk.set(NS_OVF + 'format', 'http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized')

        self.__add_network_section(envelope)
        self.__add_virtual_system(envelope)
        out = BytesIO()
        ET.ElementTree(envelope).write(out, encoding='utf-8', xml_declaration=True)

        dom = xml.dom.minidom.parseString(out.getvalue().decode('utf-8'))
        return dom.toprettyxml(indent='  ').encode('utf-8')

    def write(self, outpath):
        ovf = self.__generate_ovf()

        if os.path.exists(outpath):
            os.unlink(outpath)

        ova = tarfile.open(outpath, 'x')

        ovf_temp = tempfile.NamedTemporaryFile(delete=False)
        ovf_temp.write(ovf)
        ovf_temp.close()

        vmdk_monolith = open(self.__vmdk, 'rb')
        vmdk_stream = tempfile.NamedTemporaryFile(mode='w+b', delete=False)
        stream_optimize_vmdk(vmdk_monolith, vmdk_stream, self.__disksize)
        vmdk_stream.close()

        ova.add(ovf_temp.name, self.__vmdk_barename + '.ovf')
        ova.add(vmdk_stream.name, self.__vmdk_barename + '-drive.vmdk')
        ova.close()

        os.unlink(ovf_temp.name)
        os.unlink(vmdk_stream.name)

parser = argparse.ArgumentParser(description='convert VMDK to OVA')
parser.add_argument('vmdk', metavar='vmdkfile', type=str,
                    help='VMDK file')
parser.add_argument('-c', '--cpus', metavar='cpus', type=int,
                    help='number of CPUs')
parser.add_argument('-d', '--disksize', metavar='disksize', type=int,
                    default=10, help='disk size in GB')
parser.add_argument('-m', '--memsize', metavar='memsize', type=int,
                    default=1024, help='amount of memory in MB')
parser.add_argument('-n', '--name', metavar='name', type=str,
                    help='VM name')
parser.add_argument('-o', '--output', metavar='output', type=str,
                    help='output file')

args = parser.parse_args()
output = args.output
if output is None:
    output = os.path.splitext(args.vmdk)[0] + '.ova'
ova = OVAFile(args.vmdk, cpus=args.cpus,memsize=args.memsize, \
    disksize=args.disksize, name=args.name)
ova.write(output)
