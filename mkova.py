#!/usr/bin/env python3

from xml.etree.ElementTree import Element, SubElement, tostring
from xml.etree import ElementTree as ET
from collections import Counter
from io import BytesIO
import argparse
import tarfile
import os
import tempfile

NS_OVF = "{http://schemas.dmtf.org/ovf/envelope/1}"
NS_CIM = "{http://schemas.dmtf.org/wbem/wscim/1/common}"
NS_OVF = "{http://schemas.dmtf.org/ovf/envelope/1}"
NS_RASD = "{http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData}"
NS_VMW = "{http://www.vmware.com/schema/ovf}"
NS_VSSD = "{http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData}"
NS_XSI = "{http://www.w3.org/2001/XMLSchema-instance}"

def prettyfy(s):
    import xml.dom.minidom
    dom = xml.dom.minidom.parseString(s)
    return dom.toprettyxml(indent='  ')

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

        ET.register_namespace("ovf", "http://schemas.dmtf.org/ovf/envelope/1")
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

        i, scsi_id = self.__add_item(vhw, 'SCSI Controller 0', 'SCSI Controller',
            resource_type=6, resource_subtype='lsilogic', address=0)
        self.__add_config(i, "slotInfo.pciSlotNumber", "16")

        i, _ = self.__add_item(vhw, 'VirtualIDEController 0', 'IDE Controller',
            resource_type=5, address=0)

        i, _ = self.__add_item(vhw, 'VirtualIDEController 1', 'IDE Controller',
            resource_type=5, address=1)

        i, _ = self.__add_item(vhw, 'VirtualVideoCard', 'Virtual Video Card',
            resource_type=24, automatic_allocation='false')
        i.set(NS_OVF + 'required', 'false')
        self.__add_config(i, "enable3DSupport", "false")
        self.__add_config(i, "enableMPTSupport", "false")
        self.__add_config(i, "use3dRenderer", "automatic")
        self.__add_config(i, "useAutoDetect", "false")
        self.__add_config(i, "videoRamSizeInKB", "4096")

        i, _ = self.__add_item(vhw, 'Hard Disk 1', 'Hard Disk',
            resource_type=17, parent=scsi_id, address_on_parent=0,
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

    def __write_ovf(self, out):
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
        ET.ElementTree(envelope).write(out, encoding='utf-8', xml_declaration=True)

    def write(self, outpath):
        b = BytesIO()
        self.__write_ovf(b)
        ovf_content = prettyfy((b.getvalue().decode('utf-8')))
        if os.path.exists(outpath):
            os.unlink(outpath)

        ova = tarfile.open(outpath, 'x')

        ovf_temp = tempfile.NamedTemporaryFile(delete=False)
        ovf_temp.write(ovf_content.encode('utf-8'))
        ovf_temp.close()
        ova.add(ovf_temp.name, self.__vmdk_barename + '.ovf')
        os.unlink(ovf_temp.name)
        ova.add(self.__vmdk, self.__vmdk_barename + '-drive.vmdk')
        ova.close()

parser = argparse.ArgumentParser(description='convert VMDK to OVA')
parser.add_argument('vmdk', metavar='vmdkfile', type=str,
                    help='VMDK file')
parser.add_argument('-c', '--cpus', metavar='cpus', type=int,
                    help='number of CPUs')
parser.add_argument('-m', '--memsize', metavar='memsize', type=int,
                    default=1024, help='amount of memory in MB')
parser.add_argument('-d', '--disksize', metavar='disksize', type=int,
                    default=10, help='disk size in GB')

args = parser.parse_args()

ova = OVAFile(args.vmdk, cpus=args.cpus,memsize=args.memsize, disksize=args.disksize)
ova.write('x.ova')
