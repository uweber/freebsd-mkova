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

class OVFFile(object):

    def __init__(self):
        self.counter = Counter()
        self.__instance = 0

        ET.register_namespace("ovf", "http://schemas.dmtf.org/ovf/envelope/1")
        ET.register_namespace("cim", "http://schemas.dmtf.org/wbem/wscim/1/common")
        ET.register_namespace("ovf", "http://schemas.dmtf.org/ovf/envelope/1")
        ET.register_namespace("rasd", "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData")
        ET.register_namespace("vmw", "http://www.vmware.com/schema/ovf")
        ET.register_namespace("vssd", "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData")
        ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

        self.envelope =  Element('Envelope')
        self.envelope.set('xmlns', 'http://schemas.dmtf.org/ovf/envelope/1')
        self.envelope.set(NS_VMW + 'buildId', 'build-2494585')
        references = SubElement(self.envelope, 'References')
        f = SubElement(references, 'File')
        f.set(NS_OVF + "href", 'drive.vmdk')
        f.set(NS_OVF + "id", self.__next_id('file'))
        # f.set(NS_OVF + "size", "902624768")
        f.set(NS_OVF + "size", "874553856")

        disk_section = SubElement(self.envelope, 'DiskSection')
        SubElement(disk_section, 'Info').text = 'Virtual disk information'
        disk = SubElement(disk_section, 'Disk')
        disk.set(NS_OVF + 'capacity', '40')
        disk.set(NS_OVF + 'capacityAllocationUnits', 'byte * 2^30')
        disk.set(NS_OVF + 'diskId', 'vmdisk1')
        disk.set(NS_OVF + 'fileRef', 'file0')
        disk.set(NS_OVF + 'format', 'http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized')

        self.__add_network_section()
        self.__add_virtual_system()

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
        self.__instance += 1
        return new_e

    def __add_network_section(self):
        network_section = SubElement(self.envelope, 'NetworkSection')
        self.__add_child(network_section, 'Info', 'The list of logical networks')
        network = SubElement(network_section, 'Network')
        network.set(NS_OVF + 'name', 'VM Network')
        self.__add_child(network, 'Description', 'The VM Network network')

    def __add_virtual_system(self):
        vs = SubElement(self.envelope, 'VirtualSystem')
        vs.set(NS_OVF + 'id', self.__next_id('vsystem'))
        self.__add_child(vs, 'Info', 'A virtual machine')
        self.__add_child(vs, 'Name', 'FreeBSD 12.1-RELEASE')

        oss = SubElement(vs, 'OperatingSystemSection')
        oss.set(NS_OVF + 'id', '107')
        oss.set(NS_VMW + 'osType', 'freebsd64Guest')
        SubElement(oss, 'Info').text = 'The kind of installed guest operating system'

        product = SubElement(vs, 'ProductSection')
        SubElement(product, 'Info').text = 'Information about the installed software'
        SubElement(product, 'Product').text = 'FreeBSD OS'
        SubElement(product, 'Vendor').text = 'FreeBSD'
        SubElement(product, 'Version').text = '12.1-RELEASE'

        vhw = SubElement(vs, 'VirtualHardwareSection')
        SubElement(vhw, 'Info').text = 'Virtual hardware requirements'

        # Add system entry
        system = SubElement(vhw, 'System')
        SubElement(system, NS_VSSD + 'ElementName').text = 'Virtual Hardware Family'
        SubElement(system, NS_VSSD + 'InstanceID').text = str(self.__instance)
        SubElement(system, NS_VSSD + 'VirtualSystemIdentifier').text = 'FreeBSD 12.1-RELEASE'
        # This is the VM format type
        SubElement(system, NS_VSSD + 'VirtualSystemType').text = 'vmx-08'
        self.__instance += 1

        i = self.__add_item(vhw, '2 virtual CPU(s)', 'Number of Virtual CPUs', 
            resource_type=3, quantity=2, units='hertz * 10^6')

        i = self.__add_item(vhw, '4096MB of memory', 'Memory Size',
            resource_type=4, quantity=4096, units='byte * 2^20')

        i = self.__add_item(vhw, 'SCSI Controller 0', 'SCSI Controller',
            resource_type=6, resource_subtype='lsilogic', address=0)
        self.__add_config(i, "slotInfo.pciSlotNumber", "16")

        i = self.__add_item(vhw, 'VirtualIDEController 0', 'IDE Controller',
            resource_type=5, address=0)

        i = self.__add_item(vhw, 'VirtualIDEController 1', 'IDE Controller',
            resource_type=5, address=1)

        i = self.__add_item(vhw, 'VirtualVideoCard', 'Virtual Video Card',
            resource_type=24, automatic_allocation='false')
        i.set(NS_OVF + 'required', 'false')
        self.__add_config(i, "enable3DSupport", "false")
        self.__add_config(i, "enableMPTSupport", "false")
        self.__add_config(i, "use3dRenderer", "automatic")
        self.__add_config(i, "useAutoDetect", "false")
        self.__add_config(i, "videoRamSizeInKB", "4096")

        i = self.__add_item(vhw, 'Hard Disk 1', 'Hard Disk',
            resource_type=17, parent=3, address_on_parent=0,
            host_resource='ovf:/disk/vmdisk1')
        self.__add_config(i, "backing.writeThrough", "false")

        i = self.__add_item(vhw, 'Ethernet 1', 'VmxNet3 ethernet adapter on "VM Network"',
            resource_type=10, resource_subtype='VmxNet3', parent=3, address_on_parent=7,
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

    def __next_id(self, word):
        s = word + str(self.counter[word])
        self.counter[word] += 1
        return s

    def write(self, out):
        ET.ElementTree(self.envelope).write(out, encoding='utf-8', xml_declaration=True)

ovf = OVFFile()
b = BytesIO()
ovf.write(b)
ovf_content = prettyfy((b.getvalue().decode('utf-8')))

parser = argparse.ArgumentParser(description='convert VMDK to OVA')
parser.add_argument('vmdk', metavar='vmdkfile', type=str,
                    help='VMDK file')
parser.add_argument('-c', '--cpus', metavar='cpus', type=int,
                    help='number of CPUs')
parser.add_argument('-m', '--memsize', metavar='memsize', type=int,
                    default=1024, help='amount of memory in MB')
parser.add_argument('-d', '--disksize', metavar='disksize', type=int,
                    default=20, help='disk size in GB')

args = parser.parse_args()

print (args.vmdk)
print (args.cpus)
print (args.memsize)
print (args.disksize)

ova_path = 'x.ova'
if os.path.exists(ova_path):
    os.unlink(ova_path)

ova = tarfile.open(ova_path, 'x')

ovf_temp = tempfile.NamedTemporaryFile(delete=False)
ovf_temp.write(ovf_content.encode('utf-8'))
ovf_temp.close()
ova.add(ovf_temp.name, 'freebsd.ovf')
os.unlink(ovf_temp.name)
ova.add(args.vmdk, 'drive.vmdk')
