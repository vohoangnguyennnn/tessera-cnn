## MicroPhase A7-Lite 35T (xc7a35tfgg484-2): constraints for top.sv (spec 2, 11.2).
##
## Pins: official reference manual
##   https://fpga-docs.microphase.cn/en/latest/DEV_BOARD/A7-LITE/A7-Lite_Reference_Manual.html
## IOSTANDARD: not in the manual; LVCMOS33 as in two independent community constraint files that
## agree on every pin used here: github.com/aleiei/A7-LITE-xdc (cross-checked with the R11 schematic)
## and github.com/kisek/fpga_a7-lite_uart (a UART design run on the board at 1 Mbaud).
## DDR3 (SSTL15) sits in bank 35; the UART and keys are in bank 34 at 3.3 V.

## 50 MHz oscillator (U10). The clk_core Clocking Wizard IP constrains this input itself (20 ns, its own
## XDC), and Vivado derives the core clock from the MMCM: a second create_clock here only overrides it
## (methodology XDCC-1 / XDCC-7).
set_property -dict {PACKAGE_PIN J19 IOSTANDARD LVCMOS33} [get_ports clk_50m]

## USB-UART (CH340E). uart_tx = FPGA output, uart_rx = FPGA input.
set_property -dict {PACKAGE_PIN V2 IOSTANDARD LVCMOS33} [get_ports uart_tx]
set_property -dict {PACKAGE_PIN U2 IOSTANDARD LVCMOS33} [get_ports uart_rx]

## User key K1 used as reset: active low (pull-up, key to ground per the community constraint file).
## The manual names key K3 as a reset key but gives no pin; L18 appears only in one community file.
set_property -dict {PACKAGE_PIN AA1 IOSTANDARD LVCMOS33 PULLUP true} [get_ports rst_key_n]

## User LEDs D6, D5
set_property -dict {PACKAGE_PIN M18 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN N18 IOSTANDARD LVCMOS33} [get_ports {led[1]}]

## Asynchronous inputs go through 2-FF synchronizers in top.sv: no timing relation to the clock (spec 11.2).
set_false_path -from [get_ports {uart_rx rst_key_n}]
## LEDs are slow status outputs.
set_false_path -to [get_ports {led[*] uart_tx}]

## Configuration bank voltage (removes the CFGBVS DRC warning). Assumption: 3.3 V configuration bank,
## as on the QSPI-booting 3.3 V Artix-7 boards; check the schematic before relying on it for SPI boot.
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
