#include <cuda_runtime.h>
#include <iostream>

__global__ void fast_attention_kernel(float* q, float* k, float* v, float* out, int n) {
    int idx = blockDim.x * blockIdx.x + threadIdx.x;
    if (idx < n) {
        out[idx] = q[idx] * k[idx] + v[idx];
    }
}
