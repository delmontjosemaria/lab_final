#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>

struct ring{
    size_t capacity;
    size_t size;
    int head;
    int tail;
    uint16_t * buffer;
};

typedef struct ring ring_t;

ring_t * newRing(const size_t capacity);
void ringPush(ring_t * ring, const uint16_t item);
uint16_t ringPop(ring_t * ring);
void ringPrint(const ring_t * ring);
size_t ringOffload(ring_t * ring, void *dest, size_t n);
bool isRingFull(ring_t * ring);
void endRing(ring_t * ring);