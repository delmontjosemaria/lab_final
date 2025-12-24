#include <ringBuffer.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdio.h>

ring_t * newRing(const size_t capacity){
    ring_t * ring = malloc(sizeof(ring_t));
    ring->buffer = malloc(capacity * sizeof(uint16_t));
    ring->capacity = capacity;
    ring->size = 0;
    ring->head = 0;
    ring->tail = 0;

    return ring;
}

void ringPush(ring_t * ring, const uint16_t item){
    if(ring->tail == ring->head && ring->size == ring->capacity)
        ring->head = ++ring->head % ring->capacity;
        //size does not reduce! once it's full, it's forever full

    ring->buffer[ring->tail] = item;
    ring->tail = ++ring->tail % ring->capacity;

    if (ring->size < ring->capacity)
        ring->size++;
}

uint16_t ringPop(ring_t * ring){
    if (ring->size < 1)
        return -1;

    uint16_t item = ring->buffer[ring->head];
    ring->size--;
    
    ring->head = ++ring->head % ring->capacity;
    return item; 
}

bool isRingFull(ring_t * ring){
    return ring->size >= ring->capacity;
}

void ringPrint(const ring_t * ring){
    if (ring == NULL)
        return; 
    if(!ring->size)
        fprintf(stdout, "[∅]\n");
    else {
        fprintf(stdout, "[%d", ring->buffer[ring->head]);

        int i = (ring->head + 1) % ring->capacity;
        while (i != ring->tail) {

            fprintf(stdout, ", %d", ring->buffer[i]);
            i = (i + 1) % ring->capacity;
        }
        fprintf(stdout, "]\n");
    }
}

size_t ringOffload(ring_t * ring, void *dest, size_t n) {
    if (ring == NULL || dest == NULL || n == 0)
        return 0;
    
    size_t avail = ring->size;

    n = (n < avail) ? n : avail;
    
    if (n == 0) 
        return 0;

    uint16_t * destBytes = (uint16_t *) dest;
    
    size_t toEnd = ring->capacity - ring->head;
    size_t firstCopy = (n < toEnd) ? n : toEnd;
    size_t secondCopy = n - firstCopy;
    
    if (firstCopy > 0) 
        memcpy(destBytes, ring->buffer + ring->head, firstCopy);
    
    if (secondCopy > 0) 
        memcpy(destBytes + firstCopy, ring->buffer, secondCopy);
    

    ring->head = (ring->head + n) % ring->capacity;
    ring->size -= n;

    return n;
}

void endRing(ring_t * ring){
    free(ring->buffer);
    free(ring);
}
