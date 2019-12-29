# Overview

`freebsd-mkova` is a CLI tool to conver FreeBSD release/snapshot VMDK image to a virtual appliance file that can be easily imported by the VM software like VirtualBox or VMWare. By default virtual appliance has one CPU, 1G of memory and 10G of disk, but these parameters can be specified by CLI switches.

`freebsd-mkova` requires Python3 to work

# Usage

```
usage: freebsd-mkove.py [-h] [-c cpus] [-d disksize] [-m memsize] [-n name]
                        [-o output]
                        vmdkfile

FreeBSD release/snapshot VMDK to OVA converter

positional arguments:
  vmdkfile              VMDK file

optional arguments:
  -h, --help            show this help message and exit
  -c cpus, --cpus cpus  number of CPUs
  -d disksize, --disksize disksize
                        disk size in GB
  -m memsize, --memsize memsize
                        amount of memory in MB
  -n name, --name name  VM name
  -o output, --output output
                        output file
```
