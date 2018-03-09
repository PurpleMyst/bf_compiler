#!/usr/bin/env python3
import argparse
import ctypes
import os
import sys

from llvmlite import ir, binding as llvm

TAPE_SIZE = 30_000


def parse(bf):
    bf = iter(bf)
    result = []

    for c in bf:
        if c == "[":
            result.append(parse(bf))
        elif c == "]":
            break
        else:
            result.append(c)

    return result


def bf_to_ir(bf):
    ast = parse(bf)

    int8 = ir.IntType(8)
    int16 = ir.IntType(16)
    int32 = ir.IntType(32)
    size_t = ir.IntType(64)

    void = ir.VoidType()

    module = ir.Module(name=__file__)
    fnty = ir.FunctionType(int32, ())
    func = ir.Function(module, fnty, name="main")
    entry = func.append_basic_block(name="entry")

    builder = ir.IRBuilder(entry)

    putchar_type = ir.FunctionType(int32, (int32,))
    putchar = ir.Function(module, putchar_type, name="putchar")

    getchar_type = ir.FunctionType(int32, ())
    getchar = ir.Function(module, getchar_type, name="getchar")

    bzero_type = ir.FunctionType(void, (int8.as_pointer(), size_t))
    bzero = ir.Function(module, bzero_type, name="bzero")

    index_type = int16
    index = builder.alloca(index_type)
    builder.store(ir.Constant(index_type, 0), index)

    tape_type = int8
    tape = builder.alloca(tape_type, size=TAPE_SIZE)
    builder.call(bzero, (tape, size_t(TAPE_SIZE)))

    zero8 = int8(0)
    one8 = int8(1)

    one16 = int16(1)

    eof = int32(-1)

    def compile_instruction(instruction):
        if isinstance(instruction, list):
            # You may initially analyze this code and think that it'll error
            # due to there being multiple blocks with the same name (e.g. if we
            # have two loops, there are two "preloop" blocks), but llvmlite
            # handles that for us.

            preloop = builder.append_basic_block(name="preloop")

            # In the LLVM IR, every block needs to be terminated. Our builder
            # is still at the end of the previous block, so we can just insert
            # an unconditional branching to the preloop branch.
            builder.branch(preloop)

            builder.position_at_start(preloop)

            # load tape value
            index_value = builder.load(index)
            index_value = builder.zext(index_value, int32)
            location = builder.gep(tape, (index_value,))
            tape_value = builder.load(location)

            # check tape value
            is_zero = builder.icmp_unsigned("==", tape_value, zero8)

            # We'll now create *another* block, but we won't terminate the
            # "preloop" block until later. This is because we need a reference
            # to both the "body" and the "postloop" block to know where to
            # jump.
            body = builder.append_basic_block(name="body")
            builder.position_at_start(body)
            for inner_instruction in instruction:
                compile_instruction(inner_instruction)
            builder.branch(preloop)

            postloop = builder.append_basic_block(name="postloop")

            builder.position_at_end(preloop)
            builder.cbranch(is_zero, postloop, body)

            builder.position_at_start(postloop)
        elif instruction == "+" or instruction == "-":
            index_value = builder.load(index)
            index_value = builder.zext(index_value, int32)

            location = builder.gep(tape, (index_value,))
            value = builder.load(location)
            if instruction == "+":
                new_value = builder.sadd_with_overflow(value, one8)
            else:
                new_value = builder.ssub_with_overflow(value, one8)
            new_value = builder.extract_value(new_value, 0)
            builder.store(new_value, location)
        elif instruction == ">" or instruction == "<":
            index_value = builder.load(index)

            if instruction == ">":
                index_value = builder.add(index_value, one16)
            else:
                index_value = builder.sub(index_value, one16)

            # Takes care of overflow. I could use a `if/else` and check if
            # `index_value == TAPE_SIZE` but I couldn't be bothered to.
            index_value = builder.srem(index_value, index_type(TAPE_SIZE))

            # We need to handle underflow specially, due to the `srem`
            # operation in LLVM being a remainder, *NOT* a modulo, meaning that
            # for negative numbers the behavior is not what you would expect in
            # Python or some other language.
            underflowed = builder.icmp_signed("==", index_value, int32(-1))

            with builder.if_else(underflowed) as (then, otherwise):
                with then:
                    last_index = builder.sub(index_type(TAPE_SIZE),
                                             index_type(1))

                    builder.store(last_index, index)

                with otherwise:
                    builder.store(index_value, index)

        elif instruction == ".":
            index_value = builder.load(index)
            index_value = builder.zext(index_value, int32)

            location = builder.gep(tape, (index_value,))
            tape_value = builder.load(location)
            tape_value = builder.zext(tape_value, int32)

            builder.call(putchar, (tape_value,))
        elif instruction == ",":
            index_value = builder.load(index)
            index_value = builder.zext(index_value, int32)

            location = builder.gep(tape, (index_value,))

            char = builder.call(getchar, ())
            is_eof = builder.icmp_unsigned("==", char, eof)

            with builder.if_else(is_eof) as (then, otherwise):
                with then:
                    builder.store(zero8, location)

                with otherwise:
                    char = builder.trunc(char, tape_type)
                    builder.store(char, location)

    for instruction in ast:
        compile_instruction(instruction)

    builder.ret(int32(0))

    return module


# courtesy of the llvmlite docs
def create_execution_engine():
    """
    Create an ExecutionEngine suitable for JIT code generation on
    the host CPU.  The engine is reusable for an arbitrary number of
    modules.
    """
    # Create a target machine representing the host
    target = llvm.Target.from_default_triple()
    target_machine = target.create_target_machine()
    # And an execution engine with an empty backing module
    backing_mod = llvm.parse_assembly("")
    engine = llvm.create_mcjit_compiler(backing_mod, target_machine)
    return engine


def main():
    argp = argparse.ArgumentParser()

    argp.add_argument("filename",
                      help="The brainfuck code file.")
    group = argp.add_mutually_exclusive_group(required=True)
    group.add_argument('-r', '--run', action="store_true",
                       help="Run the brainfuck code with McJIT.")
    group.add_argument('-c', '--bitcode', action="store_true",
                       help="Emit a bitcode file.")

    argv = argp.parse_args()

    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()

    with open(argv.filename) as bf_file:
        ir_module = bf_to_ir(bf_file.read())

    binding_module = llvm.parse_assembly(str(ir_module))
    binding_module.verify()

    llvm.ModulePassManager().run(binding_module)

    # XXX: We can move this "with" into the "else" branch.
    with create_execution_engine() as engine:
        engine.add_module(binding_module)
        engine.finalize_object()
        engine.run_static_constructors()

        if argv.bitcode:
            # emit bitcode
            triple = llvm.get_default_triple()
            binding_module.triple = triple

            bitcode = binding_module.as_bitcode()

            bc_filename = os.path.splitext(argv.filename)[0]
            bc_filename += ".bc"

            with open(bc_filename, "wb") as output_file:
                output_file.write(bitcode)

            print("Wrote bitcode to", bc_filename)
        elif argv.run:
            # run inplace
            func_ptr = engine.get_function_address("main")
            asm_main = ctypes.CFUNCTYPE(ctypes.c_int)(func_ptr)
            result = asm_main()
            sys.exit(result)
        else:
            raise RuntimeError("If you can read this, you are a magician.")


if __name__ == "__main__":
    main()
