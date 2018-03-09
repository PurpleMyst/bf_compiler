# bf_compiler

Compiles brainfuck code to LLVM IR, and potentially runs it with McJIT.

## Requirements

- Python 3
- `llvmlite` (install with `python3 -m pip install --user llvmlite`)

## Usage

Place some brainfuck code into a file, and name it what you want. For the sake
of simplicity, we'll assume your file is named `example.bf`.

After installing the requirements, you can choose to:

- Run your brainfuck code directly by running `python3 bf_compiler.py --run
  example.bf`.

- Compile your brainfuck to bitcode by running `python3 bf_compiler.py --bitcode
  example.bf`, which will emit a `example.bc` file.

You can compile your LLVM bitcode to machine code by running `clang example.bc
-o example`, which will compile your LLVM bitcode directly to machine code. You
may get a warning about a "triple", but don't worry about that. ;)

## Thanks To

My friend [Zaab1t](https://github.com/Zaab1t/) for giving me the idea and the
`llvmlite` reccomendation.

I made this to get my feet wet with LLVM, and to have fun.
