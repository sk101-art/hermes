cmake_minimum_required(VERSION 3.20)
project(cuda_compiler_lab LANGUAGES CXX CUDA)

find_package(CUDA REQUIRED)
find_package(LLVM REQUIRED CONFIG)
