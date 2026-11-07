---
title: "Memory Allocator 설계 (6)"
date: 2026-11-07T11:00:00+09:00
draft: false
tags: ["시스템", "메모리"]
description: "explicit free list 구현 3편 (segregated free list)"
---

5편에서 explicit free list(LIFO)와 in-place `realloc`까지 구현했다. 이번 편은 2단계, segregated free list(A)다. 측정 방법과 환경은 5편과 같다.

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

7편에서는 이 아이디어대로 빈 블록을 크기별 BST에 담아본다.
