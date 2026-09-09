# Copyright 2025, UNSW
# SPDX-License-Identifier: BSD-2-Clause
import sys, os
import argparse
import json
import shutil
from typing import Callable, Optional
from sdfgen import SystemDescription, Sddf, DeviceTree

sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "sddf/tools/meta")
)
from board import BOARDS, add_x86_hpet

ProtectionDomain = SystemDescription.ProtectionDomain


# Adds ".elf" to elf strings
def copy_elf(source_elf: str, new_elf: str, elf_number=None):
    source_elf += ".elf"
    if elf_number != None:
        new_elf += str(elf_number)
    new_elf += ".elf"
    assert os.path.isfile(source_elf)
    return shutil.copyfile(source_elf, new_elf)


def generate(
    sdf_file: str,
    output_dir: str,
    dtb: Optional[DeviceTree],
    get_core: Callable[[str], int],
):
    uart_node = None
    ethernet_node = None
    timer_node = None
    if dtb is not None:
        uart_node = dtb.node(board.serial)
        assert uart_node is not None
        ethernet_node = dtb.node(board.ethernet)
        assert ethernet_node is not None
        timer_node = dtb.node(board.timer)
        assert timer_node is not None

    timer_driver = ProtectionDomain(
        "timer_driver", "timer_driver.elf", priority=102, cpu=get_core("timer_driver")
    )
    timer_system = Sddf.Timer(sdf, timer_node, timer_driver)

    uart_driver = ProtectionDomain(
        "serial_driver", "serial_driver.elf", priority=100, cpu=get_core("serial_driver")
    )
    serial_virt_tx = ProtectionDomain(
        "serial_virt_tx", "serial_virt_tx.elf", priority=99, cpu=get_core("serial_virt_tx")
    )
    serial_system = Sddf.Serial(
        sdf, uart_node, uart_driver, serial_virt_tx,
        enable_color=True, baud_rate=board.baud_rate,
    )

    ethernet_driver = ProtectionDomain(
        "ethernet_driver", "eth_driver.elf", priority=101, budget=100, period=400,
        cpu=get_core("ethernet_driver"),
    )
    net_virt_tx = ProtectionDomain(
        "net_virt_tx", "network_virt_tx.elf", priority=100, budget=20000,
        cpu=get_core("net_virt_tx"),
    )
    net_virt_rx = ProtectionDomain(
        "net_virt_rx", "network_virt_rx.elf", priority=99, cpu=get_core("net_virt_rx")
    )
    net_system = Sddf.Net(sdf, ethernet_node, ethernet_driver, net_virt_tx, net_virt_rx)

    client0_elf = copy_elf("echo", "echo", 0)
    client0 = ProtectionDomain(
        "client0", client0_elf, priority=97, budget=20000, cpu=get_core("client0")
    )
    client0_net_copier_elf = copy_elf("network_copy", "network_copy", 0)
    client0_net_copier = ProtectionDomain(
        "client0_net_copier", client0_net_copier_elf, priority=98, budget=20000,
        cpu=get_core("client0_net_copier"),
    )

    serial_system.add_client(client0)
    timer_system.add_client(client0)
    net_system.add_client_with_copier(client0, client0_net_copier)
    client0_lib_sddf_lwip = Sddf.Lwip(sdf, net_system, client0)

    service_pds = [
        uart_driver, serial_virt_tx, ethernet_driver, net_virt_tx, net_virt_rx,
        client0, client0_net_copier, timer_driver,
    ]
    for pd in service_pds:
        sdf.add_pd(pd)

    assert serial_system.connect()
    assert serial_system.serialise_config(output_dir)
    assert net_system.connect()
    assert net_system.serialise_config(output_dir)
    assert timer_system.connect()
    assert timer_system.serialise_config(output_dir)
    assert client0_lib_sddf_lwip.connect()
    assert client0_lib_sddf_lwip.serialise_config(output_dir)


    with open(f"{output_dir}/{sdf_file}", "w+") as f:
        f.write(sdf.render())

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dtb", required=False)
    parser.add_argument("--sddf", required=True)
    parser.add_argument("--board", required=True, choices=[b.name for b in BOARDS])
    parser.add_argument("--output", required=True)
    parser.add_argument("--sdf", required=True)
    parser.add_argument("--objcopy", required=True)
    parser.add_argument("--smp", required=True)

    args = parser.parse_args()

    board = next(filter(lambda b: b.name == args.board, BOARDS))

    sdf = SystemDescription(board.arch, board.paddr_top)
    sddf = Sddf(args.sddf)

    global obj_copy
    obj_copy = args.objcopy

    with open(args.smp, "r") as core_alloc:
        core_dict = json.load(core_alloc)
    get_core = lambda name: core_dict[name]

    dtb = None
    if board.arch != SystemDescription.Arch.X86_64:
        with open(args.dtb, "rb") as f:
            dtb = DeviceTree(f.read())

    generate(args.sdf, args.output, dtb, get_core)
