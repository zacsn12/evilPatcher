from pwn import *
from subprocess import getoutput
import sys, os
import lief

class patch64_handler:
    def __init__(self, filename, sandboxfile, debugFlag):
        context.arch = 'amd64'
        self.filename = filename
        self.ct = self.make_sandbox(sandboxfile)
        self.elf = ELF(filename)
        self.debugFlag = debugFlag

    def pr(self, a, addr):
        log.success(a + '===>' + hex(addr))

    def run(self):
        if self.debugFlag == 0:
            sys.stdout = open(os.devnull, 'w')
        self.patch_elf()
        sys.stdout = sys.__stdout__
        self.elf.save(self.filename + '.patch')
        os.system('chmod +x ' + self.filename + '.patch')
        log.success('input file: ' + self.filename)
        log.success('output file: ' + self.filename + '.patch')
        patched_elf = lief.parse(self.filename + '.patch')
        patched_elf.header.entrypoint = self.oep
        patched_elf.write(self.filename + '.patch')
        print('Patch file successfully!!!')

    def run_partial(self):
        if self.debugFlag == 0:
            sys.stdout = open(os.devnull, 'w')
        inject_code = asm('endbr64')
        inject_code += asm('push rbp')
        inject_code += self.inject_code_build() + 3 * asm('nop')
        print('============================inject code into .eh_frame============================')
        print(disasm(inject_code))
        print('.eh_frame.sh_size===>' + str(hex(self.elf.get_section_by_name('.eh_frame').header.sh_size)))
        print('inject_code.length===>' + str(hex(len(inject_code))))
        eh_frame_addr = self.elf.get_section_by_name('.eh_frame').header.sh_addr
        self.elf.write(eh_frame_addr, inject_code)
        self.edit_program_table_header()
        sys.stdout = sys.__stdout__

        self.elf.save(self.filename + '.patch')
        os.system('chmod +x ' + self.filename + '.patch')
        log.success('input file: ' + self.filename)
        log.success('output file: ' + self.filename + '.patch')
        print('Patch file successfully!!!')

    def make_sandbox(self, sandboxfile):
        sandboxCt = eval(getoutput('seccomp-tools asm ' + sandboxfile + ' -a amd64 -f inspect'))
        os.system('seccomp-tools asm ' + sandboxfile + ' -a amd64 -f raw | seccomp-tools disasm -')
        ct = []
        for i in range(len(sandboxCt) // 8):
            ct.append(u64(sandboxCt[i * 8:i * 8 + 8]))
        ct.reverse()
        return ct

    def inject_code_build(self):
        inject_code = asm(shellcraft.amd64.prctl(38, 1, 0, 0, 0))
        for i in self.ct:
            if i > 0x3fffffff:
                a = 'mov rax,' + str(i)
                inject_code += asm(a)
                inject_code += asm('push rax')
            else:
                a = 'push ' + str(i)
                inject_code += asm(a)
        inject_code += asm(shellcraft.amd64.push('rsp'))
        inject_code += asm(shellcraft.amd64.push(len(self.ct)))
        inject_code += asm('mov r10,rcx')
        inject_code += asm(shellcraft.amd64.prctl(0x16, 2, 'rsp'))
        tmp = len(self.ct) * 8 + 0x10
        inject_code += asm('add rsp,' + str(hex(tmp)))
        return inject_code

    def edit_program_table_header(self):
        program_table_header_start = self.elf.address + self.elf.header.e_phoff
        num_of_program_table_header = self.elf.header.e_phnum
        size_of_program_headers = self.elf.header.e_phentsize
        if self.debugFlag != 0:
            self.pr('program_table_header_start', program_table_header_start)
            self.pr('num_of_program_table_header', num_of_program_table_header)
            self.pr('size_of_program_headers', size_of_program_headers)

        for i in range(num_of_program_table_header):
            p_type = self.elf.get_segment(i).header.p_type
            p_flags = self.elf.get_segment(i).header.p_flags
            if p_type == 'PT_LOAD' and p_flags == 4:
                self.elf.write(program_table_header_start + i * size_of_program_headers + 4, p32(5))
                print('edit program_table_element[' + str(i) + '].p_flags===>r_x')
                
    # def patch_pie_elf(self):
    #     eh_frame_addr = self.elf.get_section_by_name('.eh_frame').header.sh_addr
    #     start_offset = self.elf.header.e_entry
    #     offset = self.elf.read(start_offset, 0x40).find(b'\x48\x8d\x3d')  # lea rdi,?
    #     offset1 = u32(self.elf.read(start_offset + offset + 3, 4))
    #     if offset1 > 0x80000000:
    #         offset1 -= 0x100000000
    #     main_addr = start_offset + offset + offset1 + 7
    #     self.pr('eh_frame_addr', eh_frame_addr)
    #     self.pr('start_offset', start_offset)
    #     self.pr('main_addr', main_addr)
    #     print('=================================edit _start==================================')
    #     print('replace _start+' + str(offset) + '------>change __libc_start_main\'s first parameter: main->.eh_frame')
    #     print(disasm(self.elf.read(start_offset + offset, 7)))
    #     s = 'lea rdi,[rip+' + str(hex(eh_frame_addr - (start_offset + offset) - 7)) + '];'
    #     print('                ||               ')
    #     print('                ||               ')
    #     print('                \/               ')
    #     print(disasm(asm(s)))

    #     inject_code = self.inject_code_build()
    #     tail = 'lea r8,[rip' + str(hex(main_addr - (eh_frame_addr + len(inject_code)) - 7)) + '];jmp r8;'
    #     inject_code += asm(tail)
    #     print('============================inject code into .eh_frame========================')
    #     print(disasm(inject_code))
    #     print('.eh_frame.sh_size===>' + str(hex(self.elf.get_section_by_name('.eh_frame').header.sh_size)))
    #     print('inject_code.length===>' + str(hex(len(inject_code))))
    #     self.elf.write(start_offset + offset, asm(s))
    #     self.elf.write(eh_frame_addr, inject_code)
    #     self.edit_program_table_header()

    def patch_elf(self):

        program_base = self.elf.address
        self.pr('program_base', program_base)

        eh_frame_addr = self.elf.get_section_by_name('.eh_frame').header.sh_addr
        start_offset = self.elf.header.e_entry
        # offset = self.elf.read(start_offset, 0x40).find(b'\x48\xc7\xc7')  # mov rdi,?
        # main_addr = u32(self.elf.read(start_offset + offset + 3, 4))
        self.pr('eh_frame_addr', eh_frame_addr)
        self.pr('start_offset', start_offset)
        # self.pr('main_addr', main_addr)
        print('=================================edit _start==================================')
        # print('replace _start+' + str(offset) + '------>change __libc_start_main\'s first parameter: main->.eh_frame')
        # print(disasm(self.elf.read(start_offset + offset, 7)))
        # s = 'mov rdi,' + str(eh_frame_addr) + ';'
        # print('                ||               ')
        # print('                ||               ')
        # print('                \/               ')
        # print(disasm(asm(s)))
        print(f'replace _start ------> change  _start->.eh_frame')
        self.oep = eh_frame_addr
        inject_code = self.inject_code_build()
        asm_code = '''
            mov rbp,rsp
            pushfq
            push rax
            push rbx
            push rcx
            push rdx
            push rsi
            push rdi
            push rbp
            push r8
            push r9
            push r10
            push r11
            push r12
            push r13
            push r14
            push r15
            '''
        tail = asm(asm_code)
        inject_code = tail + inject_code
        asm_code = '''
            pop r15
            pop r14
            pop r13
            pop r12
            pop r11
            pop r10
            pop r9
            pop r8
            pop rbp
            pop rdi
            pop rsi
            pop rdx
            pop rcx
            pop rbx
            pop rax
            popfq
            mov rsp,rbp
        '''
        tail = asm(asm_code)
        inject_code += tail
        current_addr = eh_frame_addr + len(inject_code) + 5
        inject_code += b'\xe9' + p64(0xffffffff & (start_offset - current_addr))
        print('============================inject code into .eh_frame============================')
        print(disasm(inject_code))
        print('.eh_frame.sh_size===>' + str(hex(self.elf.get_section_by_name('.eh_frame').header.sh_size)))
        print('inject_code.length===>' + str(hex(len(inject_code))))
        # self.elf.write(start_offset + offset, asm(s))
        self.elf.write(eh_frame_addr, inject_code)
        self.edit_program_table_header()

def main():
    filename = sys.argv[1]
    sandboxfile = sys.argv[2]
    debugFlag = 0
    try:
        tmp = sys.argv[3]
        debugFlag = 1
    except IndexError:
        pass
    patch64_handler(filename,sandboxfile,debugFlag).run_partial()

if __name__ == '__main__':
    main()
  
