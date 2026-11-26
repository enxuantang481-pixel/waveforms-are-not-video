/* biRISC-V 的 TCM 存储器：0x80000000 起 64 KB */
MEMORY { ram (rwx) : ORIGIN = 0x80000000, LENGTH = 0x10000 }
ENTRY(_start)
SECTIONS {
  .text : { *(.text.init) *(.text*) *(.rodata*) } > ram
  .data : { *(.data*) *(.sdata*) } > ram
  .bss  : { _bss_start = .; *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(4); _bss_end = .; } > ram
  _stack_top = ORIGIN(ram) + LENGTH(ram) - 16;
}
