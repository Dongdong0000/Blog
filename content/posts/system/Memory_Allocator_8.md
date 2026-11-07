---
title: "Memory Allocator 설계 (8)"
date: 2026-11-07T13:00:00+09:00
draft: false
tags: ["시스템", "메모리"]
description: "explicit free list 구현 5편 (A vs B 비교와 정리)"
---

7편에서 크기별 BST(B)가 종합 점수로 segregated free list(A)를 앞섰다. 이번 편에서는 두 구현을 trace별로 비교하고, 5편부터 이어온 explicit free list 구현을 정리한다.

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
