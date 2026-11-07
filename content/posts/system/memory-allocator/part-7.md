---
title: "Memory Allocator 설계 (7)"
date: 2026-11-07T12:00:00+09:00
draft: false
aliases: ["/posts/system/memory_allocator_7/"]
tags: ["시스템", "메모리"]
description: "explicit free list 구현 4편 (크기별 BST)"
---

6편의 segregated free list(A)는 class 안에서 first fit이라 best fit의 근사에 그쳤다. 이번 편은 3단계, 빈 블록을 크기순으로 담는 BST(B)다.

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
 
종합 util이 5%p 올랐다. 종합 점수로는 B의 완승이다. 하지만 trace별로 뜯어보면 살짝 이야기가 다르다. 그 이야기는 8편에서 이어간다.
