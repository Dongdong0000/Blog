---
title: "Memory Allocator 설계 (5)"
date: 2026-11-07
draft: false
tags: ["시스템", "메모리"]
description: "explicit free list 구현 2편"
---
 
4편에서 explicit free list의 설계를 정했다. 이번 편에서는 그 설계를 코드로 옮기고, 두 가지의 explict free list를 구현해봤다.
 
```text {linenos=false}
1단계     explicit free list (LIFO)   빈 블록만 훑는다
2단계     segregated free list (A)    크기가 비슷한 빈 블록만 훑는다
3단계     크기별 BST (B)               트리를 타고 내려가며 고른다
```
 
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
 
## 2단계: segregated free list (A)
 
LIFO의 문제는 맨 앞에서 아무거나 집는다는 것이었다. 크기를 보고 고르되, 전체를 훑지는 않는 방법이 필요하다. 빈 블록을 하나의 list에 몰아넣지 말고 크기대로 나눠 담는다.
 
```c
static char *seg_list[16];
```
 
list head가 16개가 됐다. 각 list는 1단계와 똑같은 이중 연결 list이고, 담는 블록의 크기 범위만 다르다.
 
### get_class
 
```c
size_t get_class(size_t size) {
    size_t index = 0;
    size--;
    size = size >> 4;
    while (size > 0 && index < 15) {
        size = size >> 1;
        index += 1;
    }
    return index;
}
```
 
`size - 1`을 16으로 나눈 몫이 몇 비트짜리인지, 즉 MSB가 어디 있는지 센다. 결과적으로 2의 거듭제곱 경계로 나뉜다.
 
```text {linenos=false}
class 0 :      16
class 1 :      17 ~     32
class 2 :      33 ~     64
class 3 :      65 ~    128
class 4 :     129 ~    256
class 5 :     257 ~    512
class 6 :     513 ~   1024
  ...
class k :  2^(k+3)+1 ~ 2^(k+4)
  ...
class 15:  262145 이상 전부
```
 
`>> 4`는 최소 블록이 16바이트라 그 아래는 볼 필요가 없어서다. 먼저 1을 빼는 건 경계값 때문이다. 빼지 않으면 32는 `32 >> 4 = 2`, 2비트라 class 2가 되어 33~64와 같은 칸에 들어간다. 1을 빼면 `31 >> 4 = 1`, class 1로 제자리를 찾는다. 범위의 위쪽 끝이 그 class에 포함되게 하는 장치다.

### insert_node, remove_node
 
```c
static void insert_node(void *bp) {
    size_t c = get_class(GET_SIZE(HDRP(bp)));
 
    SUCC(bp) = seg_list[c];
    PRED(bp) = NULL;
    if (seg_list[c] != NULL) PRED(seg_list[c]) = bp;
    seg_list[c] = bp;
}
 
static void remove_node(void *bp) {
    size_t c = get_class(GET_SIZE(HDRP(bp)));
 
    if (PRED(bp)) SUCC(PRED(bp)) = SUCC(bp);
    else seg_list[c] = SUCC(bp);
    if (SUCC(bp)) PRED(SUCC(bp)) = PRED(bp);
}
```
 
1단계 코드에서 `free_listp`가 `seg_list[c]`로 바뀐 게 전부다. 각 list 안에서는 여전히 LIFO다.

### find_fit
 
```c
static void *find_fit(size_t asize) {
    char *bp;
    size_t c = get_class(asize);
 
    for (; c < 16; c++) {                    /* 바깥: class c부터 위로 */
        for (bp = seg_list[c]; bp != NULL; bp = SUCC(bp)) {   /* 안: 그 class 순회 */
            if (GET_SIZE(HDRP(bp)) >= asize)
                return bp;
        }
    }
 
    return NULL;
}
```
 
요청 크기의 class부터 시작한다. 거기서 못 찾으면 한 칸 위 class로 올라간다. 아래 class는 볼 필요가 없다. 거기 있는 블록은 전부 요청보다 작다.
 
반대로 크기 검사가 실제로 필요한 건 **시작 class뿐**이다. 위 class에 있는 블록은 모두 시작 class의 상한보다 크고, 그 상한은 `asize` 이상이다. 그래서 한 칸만 올라가도 list의 첫 블록이 곧 답이다.
 
또 이 방식은 별다른 노력 없이 best fit에 가까워진다. 요청과 크기 범위가 비슷한 블록부터 보기 때문에, 1단계처럼 큰 블록이 작은 요청에 잘려나가는 일이 줄어든다. 다만 class 안에서는 first fit이라, 정확한 best fit은 아니고 근사다.
 
### 2단계 결과
 
| 단계 | util | thru | P |
|---|---:|---:|---:|
| + realloc in-place | 74% | 만점 | 84 |
| **A: segregated** | **78%** | 만점 | **87** |
 
처리량 만점을 유지한 채 util이 처음으로 baseline을 넘었다. 크기를 보고 고르기 시작한 효과다. 남은 아쉬움은 class 안의 first fit이다. class 하나가 2배 범위를 덮기 때문에, 600바이트 요청은 513~1024 class에서 처음 만난 맞는 블록을 쓴다. 그게 1000바이트짜리일 수도 있다. 크기 순서 자체를 자료구조에 담으면 정확한 best fit을 할 수 있다.
 
## 3단계: 크기별 BST (B)
 
빈 블록을 크기를 key로 하는 이진 탐색 트리에 넣는다. 그러면 "`asize` 이상 중 가장 작은 블록"을 트리 높이만큼만 내려가서 찾을 수 있다.
 
### 노드 설계
 
트리 노드에는 pointer가 네 개 필요하다.
 
```c
#define LEFT(bp)     (*(char **)(bp))
#define RIGHT(bp)    (*(char **)((bp) + WSIZE))
#define PARENT(bp)   (*(char **)((bp) + 2 * WSIZE))
#define BROTHER(bp)  (*(char **)((bp) + 3 * WSIZE))
```
 
```text {linenos=false}
+-----------------------+
|   size       | 0 0 0  |  헤더
+-----------------------+ <- bp
|   LEFT                |  더 작은 크기의 서브트리
+-----------------------+
|   RIGHT               |  더 큰 크기의 서브트리
+-----------------------+
|   PARENT              |  부모 노드
+-----------------------+
|   BROTHER             |  같은 크기의 다음 블록
+-----------------------+
|   size       | 0 0 0  |  푸터
+-----------------------+
```
 
헤더 4 + pointer 16 + 푸터 4 = 24바이트. 4편에서 본 것과 같은 이유로 `MINBLOCK`이 24로 커지고, `mm_malloc`과 `adjust_size`의 최솟값도 `3 * DSIZE`로 올라간다. 할당된 블록은 이 pointer들을 쓰지 않는데도, 언젠가 free될 때를 위해 24바이트를 확보해야 한다.
 
PARENT가 필요한 이유는 4편의 pred와 같다. 노드를 트리에서 빼려면 부모의 LEFT나 RIGHT를 고쳐야 한다. `coalesce`가 넘겨주는 건 블록 주소뿐이니, 부모를 찾으려고 root부터 다시 내려가지 않으려면 블록이 자기 부모를 알고 있어야 한다.
 
### 같은 크기는 어떻게 할까
 
BST는 key가 겹치는 경우가 골칫거리다. 그런데 allocator에서 같은 크기의 빈 블록은 아주 흔하다. 프로그램은 같은 구조체를 계속 할당하고 해제한다. 같은 크기를 한쪽 서브트리로 계속 보내면 트리가 한쪽으로 길게 늘어진다.
 
그래서 같은 크기는 트리에 넣지 않고, 트리 노드 하나에 BROTHER로 줄줄이 매단다.
 
```text {linenos=false}
                  [64] head ── BROTHER ──> [64] ── BROTHER ──> [64] ──> NULL
                 /    \       <── LEFT ──        <── LEFT ──
              [32]    [128]                PARENT = -1        PARENT = -1
```
 
트리에는 크기마다 대표(head) 하나만 들어간다. 트리의 크기가 빈 블록 수가 아니라 **서로 다른 크기의 수**가 된다.
 
매달린 블록(member)은 트리에 참여하지 않으니 LEFT와 PARENT 칸이 놀게 된다. 이걸 재활용했다.
 
- `LEFT`: chain에서 바로 앞 블록. head일 수도 있다. 이중 연결 list의 pred 역할이다.
- `PARENT = -1`: "나는 트리 노드가 아니라 member다"라는 표시. 진짜 주소로 -1이 나올 일은 없으니 sentinel로 쓴다.
pointer를 하나도 늘리지 않고 양방향 chain을 얻었다.
 
### insert_node
 
```c
static void insert_node(void *bp) {
    if (!tree_root) {
        tree_root = bp;
        LEFT(bp) = NULL;
        RIGHT(bp) = NULL;
        PARENT(bp) = NULL;
        BROTHER(bp) = NULL;
        return;
    }
 
    void *parent = tree_root;
    while (1) {
        if (GET_SIZE(HDRP(parent)) > GET_SIZE(HDRP(bp))) {
            if (LEFT(parent) == NULL) {
                LEFT(parent) = bp;
                LEFT(bp) = NULL;
                RIGHT(bp) = NULL;
                BROTHER(bp) = NULL;
                PARENT(bp) = parent;
                break;
            }
            else {
                parent = LEFT(parent);
            }
        }
        else if (GET_SIZE(HDRP(parent)) < GET_SIZE(HDRP(bp))) {
            if (RIGHT(parent) == NULL) {
                RIGHT(parent) = bp;
                LEFT(bp) = NULL;
                RIGHT(bp) = NULL;
                BROTHER(bp) = NULL;
                PARENT(bp) = parent;
                break;
            }
            else {
                parent = RIGHT(parent);
            }
        }
        else if (GET_SIZE(HDRP(parent)) == GET_SIZE(HDRP(bp))) {
            while (BROTHER(parent) != NULL) {
                parent = BROTHER(parent);
            }
            BROTHER(parent) = bp;
            LEFT(bp) = parent;
            RIGHT(bp) = NULL;
            PARENT(bp) = (char *)-1;
            BROTHER(bp) = NULL;
            break;
        }
    }
}
```
 
### remove_node
 
빼는 블록이 어떤 처지인지에 따라 세 갈래로 나뉜다.
 
**1. member일 때: chain에서만 뺀다**
 
```c
    if (PARENT(bp) == (char *)-1) {
        BROTHER(LEFT(bp)) = BROTHER(bp);
        if (BROTHER(bp) != NULL)
            LEFT(BROTHER(bp)) = LEFT(bp);
        return;
    }
```

**2. head인데 member가 있을 때: 첫 member를 승격한다**
 
```c
    if (BROTHER(bp) != NULL) {
        LEFT(BROTHER(bp)) = LEFT(bp);
        RIGHT(BROTHER(bp)) = RIGHT(bp);
        PARENT(BROTHER(bp)) = PARENT(bp);
 
        if (LEFT(bp) != NULL) PARENT(LEFT(bp)) = BROTHER(bp);
        if (RIGHT(bp) != NULL) PARENT(RIGHT(bp)) = BROTHER(bp);
 
        if (PARENT(bp) != NULL) {
            if (LEFT(PARENT(bp)) == bp) LEFT(PARENT(bp)) = BROTHER(bp);
            else RIGHT(PARENT(bp)) = BROTHER(bp);
        }
        else tree_root = BROTHER(bp);
 
        return;
    }
```
 
```text {linenos=false}
전:        P                          후:        P
           |                                     |
          [64]h ─> [64]m1 ─> [64]m2             [64]m1 ─> [64]m2
         /    \                                 /    \
       L        R                             L        R
```
 
**3. 혼자인 head일 때: 진짜로 트리에서 뺀다**
 
```c
    if (LEFT(bp) == NULL && RIGHT(bp) == NULL) {            /* 자식 0개 */
        if (PARENT(bp) == NULL) { tree_root = NULL; return; }
 
        if (LEFT(PARENT(bp)) == bp) LEFT(PARENT(bp)) = NULL;
        else RIGHT(PARENT(bp)) = NULL;
    }
    else if (LEFT(bp) != NULL && RIGHT(bp) == NULL) {       /* 왼쪽 자식만 */
        PARENT(LEFT(bp)) = PARENT(bp);
 
        if (PARENT(bp) == NULL) { tree_root = LEFT(bp); return; }
 
        if (LEFT(PARENT(bp)) == bp) LEFT(PARENT(bp)) = LEFT(bp);
        else RIGHT(PARENT(bp)) = LEFT(bp);
    }
    else if (LEFT(bp) == NULL && RIGHT(bp) != NULL) {       /* 오른쪽 자식만 */
        PARENT(RIGHT(bp)) = PARENT(bp);
 
        if (PARENT(bp) == NULL) { tree_root = RIGHT(bp); return; }
 
        if (LEFT(PARENT(bp)) == bp) LEFT(PARENT(bp)) = RIGHT(bp);
        else RIGHT(PARENT(bp)) = RIGHT(bp);
    }
```
 
자식이 없으면 부모에서 끊고, 하나면 그 자식을 자기 자리에 올린다. root였다면 부모 대신 `tree_root`를 고친다.
 
자식이 둘이면 successor, 즉 오른쪽 서브트리에서 가장 작은 노드를 자기 자리에 올린다.
 
```c
    else if (LEFT(bp) != NULL && RIGHT(bp) != NULL) {       /* 자식 2개 */
        void *succ = RIGHT(bp);
 
        if (LEFT(succ) == NULL) {               /* 오른쪽 자식이 곧 successor */
            LEFT(succ) = LEFT(bp);
            PARENT(LEFT(bp)) = succ;
            PARENT(succ) = PARENT(bp);
            if (PARENT(bp) == NULL) tree_root = succ;
            else if (LEFT(PARENT(bp)) == bp) LEFT(PARENT(bp)) = succ;
            else RIGHT(PARENT(bp)) = succ;
            return;
        }
 
        while (LEFT(succ) != NULL) succ = LEFT(succ);
 
        LEFT(PARENT(succ)) = RIGHT(succ);       /* successor를 원래 자리에서 떼고 */
        if (RIGHT(succ) != NULL)
            PARENT(RIGHT(succ)) = PARENT(succ);
 
        LEFT(succ) = LEFT(bp);                  /* bp의 자식들을 물려받고 */
        PARENT(LEFT(bp)) = succ;
        RIGHT(succ) = RIGHT(bp);
        PARENT(RIGHT(bp)) = succ;
 
        PARENT(succ) = PARENT(bp);              /* bp의 부모와 연결 */
        if (PARENT(bp) == NULL) tree_root = succ;
        else if (LEFT(PARENT(bp)) == bp) LEFT(PARENT(bp)) = succ;
        else RIGHT(PARENT(bp)) = succ;
    }
```
 
### find_fit
 
```c
static void *find_fit(size_t asize) {
    void *best = NULL;
    void *cur = tree_root;
 
    while (cur != NULL) {
        if (GET_SIZE(HDRP(cur)) >= asize) {   /* fit 후보 */
            best = cur;                        /* 기억하고 */
            cur = LEFT(cur);                   /* 더 작은 fit 찾으러 왼쪽 */
        }
        else {                                 /* 너무 작음 */
            cur = RIGHT(cur);                  /* 더 큰 거 찾으러 오른쪽 */
        }
    }
 
    return best;
}
```
 
맞는 노드를 만나면 일단 후보로 적어두고, 더 작으면서 맞는 게 있는지 왼쪽으로 내려간다. 너무 작으면 오른쪽으로 간다. NULL에 닿았을 때 마지막으로 적어둔 후보가 "`asize` 이상 중 가장 작은 것"이다. 트리 노드만 따라가니 chain은 볼 일이 없고, 비용은 트리 높이에 비례한다.
 
### 디버깅: 트리는 조용히 망가진다
 
pointer를 네 개씩 고치다 보면 한 군데만 틀려도 트리가 조용히 꼬인다. 증상은 한참 뒤 엉뚱한 곳에서 나타난다. 그래서 매 연산 뒤에 불변식을 검사하는 함수를 만들어 범위를 좁혀갔다.
 
검사 항목은 네 가지다. 자식의 PARENT가 정말 나를 가리키는지, 노드가 힙 안에 있는지, 왼쪽 < 나 < 오른쪽인지, 그리고 무한히 내려가지 않는지(cycle). 이걸로 잡은 주요 버그가 두 개 있었다.
 
**1. root 초기화 누락**
 
빈 트리에 첫 블록을 root로 넣을 때 LEFT/RIGHT/PARENT/BROTHER를 초기화하지 않았다. 그 블록의 payload에는 예전 사용자 데이터가 그대로 남아 있다. PARENT 자리의 쓰레기 값이 하필 `(char *)-1`로 읽히자, `remove_node`가 root를 member로 착각해 chain에서 빼려다 segfault가 났다. 위 코드의 첫 `if` 블록이 그 수정이다.
 
**2. MINBLOCK 미조정**
 
2단계의 `MINBLOCK 16`을 그대로 두었다. 그러자 `place`가 16~23바이트짜리 자투리를 빈 블록으로 쪼개 남겼고, 거기에 pointer 4개(16바이트)를 쓰면서 푸터와 다음 블록의 헤더를 덮어썼다. 헤더가 오염되자 `find_fit`이 힙 밖 주소를 돌려줬다.
 
트리의 모든 연결은 양방향이어야 한다. 부모가 자식을 가리키면 자식도 부모를 가리켜야 하고, 한쪽만 고치면 dangling pointer나 cycle이 생긴다. 디버깅 시간의 대부분이 이 역방향 연결 누락을 찾는 데 들었다.
 
### 3단계 결과
 
| 단계 | util | thru | P |
|---|---:|---:|---:|
| A: segregated | 78% | 만점 | 87 |
| **B: BST** | **83%** | 만점 | **90** |
 
종합 util이 5%p 올랐다. 종합 점수로는 B의 완승이다. trace별로 뜯어보면 살짝 이야기가 다르다.
 
## A vs B, trace별로 보기
 
### util
 
| trace | 패턴 | A (segregated) | B (BST) |
|---|---|---:|---:|
| 0 amptjp | 일반 | 98% | 99% |
| 1 cccp | 일반 | 98% | 99% |
| 2 cp-decl | 일반 | 97% | 99% |
| 3 expr | 일반 | 99% | 99% |
| 4 coalescing | binary | 66% | 66% |
| 5 random | 다양 | 93% | 96% |
| 6 random2 | 다양 | 90% | 95% |
| 7 binary | binary | 55% | 55% |
| 8 binary2 | binary | 51% | 51% |
| 9 realloc | realloc | 46% | **87%** |
| 10 realloc2 | realloc | 67% | 67% |
| **종합** | | **78%** | **83%** |
 
### thru (Kops)
 
| trace | A | B | |
|---|---:|---:|---|
| 0 amptjp | 29,749 | 35,410 | B 빠름 |
| 2 cp-decl | 29,056 | 33,373 | B 빠름 |
| 4 coalescing | 54,299 | 97,627 | B 빠름 |
| 7 binary | 45,403 | 3,299 | **A가 약 14배** |
| 8 binary2 | 49,241 | 1,692 | **A가 약 29배** |
| 9 realloc | 66,181 | 108,197 | B 빠름 |
| 10 realloc2 | 93,210 | 123,614 | B 빠름 |
 
### 1. binary 패턴에서 B가 수십 배 느렸다
 
trace 7, 8에서 B는 A보다 약 14배, 29배 느렸다.
 
처음에는 트리가 한쪽으로 기울어서라고 생각했다. 균형을 맞추지 않는 BST는 입력에 따라 한 줄로 늘어져 O(n)이 되니까. 그런데 다시 보니 이 설계에서는 말이 안 된다. binary 패턴에서 해제되는 블록은 **전부 같은 크기**다. 같은 크기는 트리에 들어가지 않고 BROTHER chain에 매달린다. 트리 노드는 하나뿐이고, 기울어질 트리 자체가 없다.
 
범인은 `insert_node`의 그 `while` 한 줄이었다.
 
```c
while (BROTHER(parent) != NULL) {
    parent = BROTHER(parent);
}
```
 
같은 크기를 만나면 chain **끝까지** 걸어가서 붙인다. chain에 k개가 매달려 있으면 k걸음이다. 같은 크기 블록 n개를 연달아 해제하면 1 + 2 + ... + n, O(n²)이 된다. 트리는 멀쩡한데 chain이 linked list의 탐색 문제를 그대로 다시 만든 것이다.
 
binary 패턴을 흉내 내서 chain을 걸은 횟수를 직접 세어봤다. 두 크기를 번갈아 n쌍 할당하고, 한쪽을 전부 해제한 뒤 조금 더 큰 크기를 n번 요청하는 패턴이다.
 
| 패턴 | chain 걸음 | A | B | B (head 뒤 삽입) |
|---|---:|---:|---:|---:|
| (64, 448) → 512, n=2000 | 1,933,052 | 1.06 ms | 7.40 ms | 0.93 ms |
| (16, 112) → 128, n=4000 | 7,910,443 | 0.33 ms | 16.90 ms | 0.19 ms |
 
n을 두 배로 늘리자 걸음 수가 네 배가 됐다. O(n²) 그대로다. trace 8(binary2)이 trace 7보다 더 심하게 느려진 것도 블록이 작아서 같은 크기의 블록이 더 많이 쌓이는 패턴이기 때문으로 보인다.
 
고치는 건 간단하다. 끝까지 걸어가지 말고 head 바로 뒤에 끼워 넣으면 된다.
 
```c
else if (GET_SIZE(HDRP(parent)) == GET_SIZE(HDRP(bp))) {
    BROTHER(bp) = BROTHER(parent);
    if (BROTHER(parent) != NULL) LEFT(BROTHER(parent)) = bp;
    BROTHER(parent) = bp;
    LEFT(bp) = parent;
    RIGHT(bp) = NULL;
    PARENT(bp) = (char *)-1;
    break;
}
```
 
1단계 LIFO의 `insert_node`와 같은 모양이다. 끼워 넣을 자리의 뒤 블록이 있으면 그 블록의 LEFT(=pred)를 새 블록으로 바꿔주는 것만 잊지 않으면 된다. 같은 크기 안의 순서는 FIFO에서 LIFO로 바뀌지만, 크기가 같으니 어느 블록을 고르든 util에는 차이가 없다. 위 표의 마지막 열처럼 chain 걸음이 0이 되고, A보다도 빨라졌다. 같은 불변식 검사를 붙여 돌려도 문제가 없었다.

## 정리
 
| 단계 | 전략 | util | thru | P |
|---|---|---:|---:|---:|
| baseline | implicit, first fit | 74% | — | 72 |
| 1단계 | explicit (LIFO) | 71% | 만점 | 82 |
| | + realloc in-place | 74% | 만점 | 84 |
| 2단계 | **A**: segregated (16 class) | 78% | 만점 | 87 |
| 3단계 | **B**: 크기별 BST | 83% | 만점 | 90 |
 
implicit에서 explicit으로 가며 처리량을 얻었고, segregated에서 BST로 가며 이용률을 얻었다. 단계마다 남긴 것도 있다.
 
- **explicit (LIFO)**: 할당된 블록을 건너뛰어 탐색이 크게 줄었다. 대신 맨 앞에서 아무거나 집는 정책 때문에 이용률이 조금 떨어졌다.
- **A: segregated**: 크기를 보고 고르기 시작해 이용률이 baseline을 넘었다. class 안에서는 아직 first fit이다.
- **B: BST**: 정확한 best fit을 트리 높이만큼의 탐색으로 해낸다. 대신 최소 블록이 커졌고, 같은 크기 chain을 끝까지 걷는 삽입이 binary 패턴에서 O(n²)이 됐다.
그리고 자료구조로 해결할 수 없는 것도 확인했다. 빈 블록이 살아 있는 블록 사이에 흩어져 있고 하나하나가 요청보다 작다면, 어떤 정책도 그 공간을 쓰지 못한다. compaction이 불가능한 C의 `malloc`이 안고 가는 근본적인 한계다.
 
개선할 여지도 남아 있다. `find_fit`이 head를 돌려주니 같은 크기의 member가 있어도 매번 승격이 일어난다. member가 있으면 member를 돌려주면 트리를 건드리지 않고 O(1)로 뺄 수 있다. 또 이번 trace에서는 드러나지 않았지만, 크기가 계속 커지는 순서로 빈 블록이 들어오면 트리 자체가 한 줄로 기운다. 그 경우까지 막으려면 red-black tree 같은 균형 트리가 필요하다.
