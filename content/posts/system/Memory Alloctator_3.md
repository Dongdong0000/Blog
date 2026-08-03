---
title: "Memory Allocator 설계 (3)"
date: 2026-08-03
draft: false
tags: ["시스템", "메모리"]
description: "implicit free list 구현 2편"
---

## 코드 작성

### mm_malloc
```c
void *mm_malloc(size_t size)
{
    size_t asize;
    size_t extendsize;
    char *bp;

    /* size 예외 체크 및 정렬화 */
    if (size == 0) return NULL;
    if (size <= DSIZE) asize = 2 * DSIZE;
    else asize = DSIZE * ((size + DSIZE + (DSIZE - 1)) / DSIZE);

    if ((bp = find_fit(asize)) != NULL) {
        place(bp, asize);
        return bp;
    }

    extendsize = (asize > CHUNKSIZE) ? asize : CHUNKSIZE;
    if ((bp = extend_heap(extendsize / WSIZE)) == NULL) return NULL;
    place(bp, asize);
    return bp;
}
```
지금 함수마다 하는 역할이 정확히 분리되어 있다. `find_fit` 함수는 free block 위치를 찾기**만**하고, 실제로 배치는 `place` 함수를 통해 이루어 진다. free block을 찾지 못했을 때에는 `extend_heap` 함수를 이용해 heap 크기를 늘린 후에 배치를 한다. 
### find_fit
```c
static void *find_fit(size_t asize) {
    char *bp;

    for (bp = heap_listp; GET_SIZE(HDRP(bp)) > 0; bp = NEXT_BLKP(bp)) {
        if (!GET_ALLOC(HDRP(bp)) && GET_SIZE(HDRP(bp)) >= asize) return bp;
    }

    return NULL;
}
```
구현한 `find_fit` 함수는 first fit 정책을 따라서 구현했다.
### place
```c
static void place(void *bp, size_t asize) {
    size_t csize = GET_SIZE(HDRP(bp));

    if ((csize - asize) >= MINBLOCK) {
        PUT(HDRP(bp), PACK(asize, 1));
        PUT(FTRP(bp), PACK(asize, 1));
        bp = NEXT_BLKP(bp);
        PUT(HDRP(bp), PACK((csize - asize), 0));
        PUT(FTRP(bp), PACK((csize - asize), 0));
    }
    else {
        PUT(HDRP(bp), PACK(csize, 1));
        PUT(FTRP(bp), PACK(csize, 1));
    }
}
```
`mm_malloc` 함수 설명할 때 말했듯이, `place` 함수는 그 자리에 배치하는 역할만 한다. 해당 block의 크기가 할당하려는 size보다 훨씬 크다면(또 다른 block으로 쪼갤 수 있는 크기만큼) 해당 blcok을 쪼개서 2개의 block으로 만든다.
### coalesce
```c
static void *coalesce(void *bp) {
    size_t prev_alloc = GET_ALLOC(FTRP(PREV_BLKP(bp)));
    size_t next_alloc = GET_ALLOC(HDRP(NEXT_BLKP(bp)));
    size_t size = GET_SIZE(HDRP(bp));

    if (prev_alloc && next_alloc) {              /* Case 1 */
        return bp;
    }
    else if (prev_alloc && !next_alloc) {        /* Case 2 */
        size += GET_SIZE(HDRP(NEXT_BLKP(bp)));
        PUT(HDRP(bp), PACK(size, 0));
        PUT(FTRP(bp), PACK(size, 0));
    }
    else if (!prev_alloc && next_alloc) {        /* Case 3 */
        size += GET_SIZE(HDRP(PREV_BLKP(bp)));
        PUT(FTRP(bp), PACK(size, 0));
        PUT(HDRP(PREV_BLKP(bp)), PACK(size, 0));
        bp = PREV_BLKP(bp);
    }
    else {                                       /* Case 4 */
        size += GET_SIZE(HDRP(PREV_BLKP(bp))) + GET_SIZE(FTRP(NEXT_BLKP(bp)));
        PUT(HDRP(PREV_BLKP(bp)), PACK(size, 0));
        PUT(FTRP(NEXT_BLKP(bp)), PACK(size, 0));
        bp = PREV_BLKP(bp);
    }
    return bp;
}
```
합병할 때는 인접한 두 블록의 상태에 따라 네 가지 경우가 나온다.

**Case 1 — 양쪽 다 할당됨**

합칠 이웃이 없다. 방금 해제한 블록은 이미 `mm_free`에서 빈 상태로 표시됐으니 더 손댈 것이 없다. `bp`를 그대로 돌려준다.

**Case 2 — 뒤가 비어 있음**

뒤 블록의 크기를 지금 크기에 더한다. 그러면 합쳐진 블록의 헤더는 지금 자리 그대로고, 푸터만 뒤 블록의 푸터 위치로 옮겨간다.

**Case 3 — 앞이 비어 있음**

이번엔 앞 블록에 붙는다. 합쳐진 블록의 시작이 앞 블록의 시작으로 당겨지므로, 헤더는 앞 블록의 헤더 자리로, 푸터는 지금 자리로 정해진다.

**Case 4 — 양쪽 다 비어 있음**

앞뒤를 모두 흡수한다. 앞 블록과 뒤 블록의 크기를 둘 다 더한다.

네 경우 모두, 함수가 끝나면 `bp`는 합쳐진 하나의 빈 블록을 가리킨다. 그래서 `extend_heap`도 `mm_free`도 `coalesce`의 반환값을 그대로 받아 쓰면 된다.

### mm_free
```c
void mm_free(void *ptr)
{
    size_t size = GET_SIZE(HDRP(ptr));
    PUT(HDRP(ptr), PACK(size, 0));
    PUT(FTRP(ptr), PACK(size, 0));
    coalesce(ptr);
}
```
해당 block을 free blcok으로 만든 후에 `coalesce` 함수 호출해서 양 옆에 빈 block이 있으면 병합한다.
### mm_realloc
```c
void *mm_realloc(void *ptr, size_t size)
{
    if (ptr == NULL)
        return mm_malloc(size);
    if (size == 0) {
        mm_free(ptr);
        return NULL;
    }

    /* 새 block 할당 */
    void *newptr = mm_malloc(size);
    if (newptr == NULL)
        return NULL;

    /* 기존 데이터 복사 (old/new 중 작은 만큼) */
    size_t old_size = GET_SIZE(HDRP(ptr)) - DSIZE;   /* payload 크기 = 전체 - header/footer */
    size_t copy_size = (old_size < size) ? old_size : size;
    memcpy(newptr, ptr, copy_size);

    /* 기존 block 반납 */
    mm_free(ptr);

    return newptr;
}
```
또 다른 block을 생성 한 후, 데이터 복사까지 마치면 원래 block은 free blcok으로 만든다.

**여기까지가 implicit free list 구현이며 다음 편에서는 이어서 explicit free list 구현해볼 예정이다.**