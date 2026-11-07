---
title: "Memory Allocator 설계 (5)"
date: 2026-11-07T10:00:00+09:00
draft: false
aliases: ["/posts/system/memory_allocator_5/"]
tags: ["시스템", "메모리"]
description: "explicit free list 구현 2편 (LIFO)"
---

4편에서 explicit free list의 설계를 정했다. 이번 편부터 그 설계를 코드로 옮기고, 빈 블록을 엮는 방식을 세 단계로 바꿔가며 구현해봤다. 내용이 길어서 단계별로 나눠 싣는다.

```text {linenos=false}
1단계     explicit free list (LIFO)   빈 블록만 훑는다
2단계     segregated free list (A)    크기가 비슷한 빈 블록만 훑는다
3단계     크기별 BST (B)               트리를 타고 내려가며 고른다
```

1단계는 이번 5편, 2단계는 6편, 3단계는 7편에서 다루고, 8편에서 A와 B를 trace별로 비교하며 정리한다.

단계마다 바뀌는 건 거의 `insert_node`, `remove_node`, `find_fit` 세 함수뿐이다. `find_fit`은 찾기만, `place`는 배치만 하도록 나눠둔 덕분이다. 추가로 자료구조 관점에서 실험을 진행해봤다. **빈 블록을 어떤 자료구조로 엮느냐가 allocator 성능에 어떤 영향을 주는가?**
 
## 측정 방법
 
- **util (메모리 이용률)**: 실행 중 가장 많이 살아 있던 payload 합을 힙 크기로 나눈 값. 공간을 얼마나 알뜰하게 쓰는가.
- **thru (처리량)**: 초당 처리한 연산 수. 얼마나 빠른가.
둘을 합친 점수가 Perf index(P)다. 환경은 Ubuntu 24.04, GCC 13.3, 시리즈 기준대로 `-m32` 32비트 빌드다.
 
## 1단계: explicit free list (LIFO)
 
### insert_node, remove_node
 
```c
static void insert_node(void *bp) {
    SUCC(bp) = free_listp;
    PRED(bp) = NULL;
    if (free_listp != NULL) PRED(free_listp) = bp;
    free_listp = bp;
}
 
static void remove_node(void *bp) {
    if (PRED(bp)) SUCC(PRED(bp)) = SUCC(bp);
    else free_listp = SUCC(bp);
    if (SUCC(bp)) PRED(SUCC(bp)) = PRED(bp);
}
```
 
`insert_node`는 LIFO라 항상 맨 앞에 넣는다. 원래 head였던 블록의 pred를 새 블록으로 바꾸는 것만 잊지 않으면 된다.
 
`remove_node`는 앞뒤 노드가 서로를 가리키게 만들어 자기를 건너뛰게 한다. 앞 노드가 없으면 자기가 head였다는 뜻이니 `free_listp`를 옮긴다.
 
### coalesce
 
```c
static void *coalesce(void *bp) {
    size_t prev_alloc = GET_ALLOC(FTRP(PREV_BLKP(bp)));
    size_t next_alloc = GET_ALLOC(HDRP(NEXT_BLKP(bp)));
    size_t size = GET_SIZE(HDRP(bp));
 
    if (prev_alloc && next_alloc) {              /* Case 1 */
        insert_node(bp);
        return bp;
    }
    else if (prev_alloc && !next_alloc) {        /* Case 2 */
        remove_node(NEXT_BLKP(bp));
        size += GET_SIZE(HDRP(NEXT_BLKP(bp)));
        PUT(HDRP(bp), PACK(size, 0));
        PUT(FTRP(bp), PACK(size, 0));
    }
    else if (!prev_alloc && next_alloc) {        /* Case 3 */
        remove_node(PREV_BLKP(bp));
        size += GET_SIZE(HDRP(PREV_BLKP(bp)));
        PUT(FTRP(bp), PACK(size, 0));
        PUT(HDRP(PREV_BLKP(bp)), PACK(size, 0));
        bp = PREV_BLKP(bp);
    }
    else {                                       /* Case 4 */
        remove_node(PREV_BLKP(bp));
        remove_node(NEXT_BLKP(bp));
        size += GET_SIZE(HDRP(PREV_BLKP(bp))) + GET_SIZE(FTRP(NEXT_BLKP(bp)));
        PUT(HDRP(PREV_BLKP(bp)), PACK(size, 0));
        PUT(FTRP(NEXT_BLKP(bp)), PACK(size, 0));
        bp = PREV_BLKP(bp);
    }
    insert_node(bp);
    return bp;
}
```
 
3편과 비교하면 두 가지가 더해졌다.
 
- 흡수되는 이웃은 list에서 뺀다. 합쳐진 뒤에는 독립된 블록이 아니기 때문이다.
- 합쳐진 결과는 list에 넣는다. Case 1처럼 합칠 게 없어도 자기 자신을 넣는다.
이렇게 `coalesce`가 list 삽입까지 책임지니, 빈 블록을 만들어 `coalesce`에 넘기기만 하는 `extend_heap`과 `mm_free`는 한 줄도 바뀌지 않는다.

### find_fit, place
 
```c
static void *find_fit(size_t asize) {
    char *bp;
 
    for (bp = free_listp; bp != NULL; bp = SUCC(bp)) {
        if (!GET_ALLOC(HDRP(bp)) && GET_SIZE(HDRP(bp)) >= asize) return bp;
    }
 
    return NULL;
}
```
```c
static void place(void *bp, size_t asize) {
    size_t csize = GET_SIZE(HDRP(bp));
 
    remove_node(bp);
 
    if ((csize - asize) >= MINBLOCK) {
        PUT(HDRP(bp), PACK(asize, 1));
        PUT(FTRP(bp), PACK(asize, 1));
        bp = NEXT_BLKP(bp);
        PUT(HDRP(bp), PACK((csize - asize), 0));
        PUT(FTRP(bp), PACK((csize - asize), 0));
        insert_node(bp);
    }
    else {
        PUT(HDRP(bp), PACK(csize, 1));
        PUT(FTRP(bp), PACK(csize, 1));
    }
}
```
 
### 1단계 결과
 
| 단계 | util | thru | P |
|---|---:|---:|---:|
| baseline (implicit) | 74% | — | 72 |
| explicit (LIFO) | 71% | 만점 | 82 |
 
처리량은 기대대로 만점이 됐다. 할당된 블록을 건너뛰게 되면서 탐색 비용이 사라졌다.
 
그런데 util이 74%에서 71%로 조금 떨어졌다. 4편에서 LIFO의 단점으로 "주소와 무관하게 섞여 단편화가 더 생길 수 있다"고 적었는데, 그게 숫자로 나타난 것으로 보인다. LIFO + first fit은 list 맨 앞에 있는 블록이 들어가기만 하면 크기를 따지지 않고 쓴다. 방금 반납된 큰 블록이 작은 요청에 잘려나가면, 정작 그 크기가 필요한 요청이 왔을 때는 맞는 자리가 없어 힙을 늘리게 된다.
 
### mm_realloc
 
util을 되찾기 전에 `realloc`부터 손봤다.
 
```c
void *mm_realloc(void *ptr, size_t size)
{
    if (ptr == NULL) return mm_malloc(size);
    if (size == 0) { mm_free(ptr); return NULL; }
 
    size_t asize = adjust_size(size);
    size_t csize = GET_SIZE(HDRP(ptr));
 
    if (asize <= csize) return ptr;    /* CASE 1 */
 
    char* next = NEXT_BLKP(ptr);
    size_t next_size = GET_SIZE(HDRP(next));
    size_t next_alloc = GET_ALLOC(HDRP(next));
 
    if (!next_alloc && (csize + next_size) >= asize) {   /* CASE 2 */
        remove_node(next);
        PUT(HDRP(ptr), PACK(csize + next_size, 1));
        PUT(FTRP(ptr), PACK(csize + next_size, 1));
        return ptr;
    }
 
    /* fallback */
    void *newptr = mm_malloc(size);
    if (newptr == NULL) return NULL;
    size_t old_payload = csize - DSIZE;
    size_t copy_size = (old_payload < size) ? old_payload : size;
    memcpy(newptr, ptr, copy_size);
    mm_free(ptr);
    return newptr;
}
```
 
3편의 `realloc`은 무조건 새로 할당하고 복사했다. 이제는 그 전에 두 가지를 확인한다.
 
- **CASE 1**: 지금 블록이 이미 충분히 크면 그대로 돌려준다. 줄이는 요청이나, 정렬 때문에 원래 여유가 있던 경우다.
- **CASE 2**: 바로 뒤 블록이 비어 있고 둘을 합치면 들어가면, 뒤 블록을 list에서 빼고 흡수한다. 데이터는 제자리에 있으니 복사가 필요 없다.
`asize` 계산은 `mm_malloc`과 정확히 같아야 한다. 둘이 어긋나면 "지금 블록으로 충분한가"를 `mm_malloc`과 다른 기준으로 판단하게 되고, 실제로는 모자란 블록을 그대로 돌려줘 데이터가 이웃을 덮어쓸 수 있다.
 
| 단계 | util | thru | P |
|---|---:|---:|---:|
| explicit (LIFO) | 71% | 만점 | 82 |
| + realloc in-place | 74% | 만점 | 84 |
 
복사를 피하니 realloc trace(9, 10)의 처리량이 크게 좋아졌고, util도 baseline 수준으로 돌아왔다. 새 블록을 따로 잡지 않으니 옛 블록이 구멍으로 남을 일도 줄어든다.

LIFO로 처리량은 얻었지만, 맨 앞에서 아무거나 집는 정책 때문에 이용률은 아직 아쉽다. 6편에서는 빈 블록을 크기별로 나눠 담는 segregated free list로 이 문제를 다룬다.
