---
title: "Memory Allocator 설계 (4)"
date: 2026-09-23T13:00:00+09:00
draft: false
aliases: ["/posts/system/memory-alloctator_4/"]
tags: ["시스템", "메모리"]
description: "explicit free list 구현 1편"
---

## implicit free list의 한계

3편까지 만든 allocator는 제대로 동작한다. 그런데 `find_fit`을 다시 보면 걸리는 부분이 있다.

```c
for (bp = heap_listp; GET_SIZE(HDRP(bp)) > 0; bp = NEXT_BLKP(bp)) {
    if (!GET_ALLOC(HDRP(bp)) && GET_SIZE(HDRP(bp)) >= asize) return bp;
}
```

우리가 찾는 건 빈 블록인데, 루프는 힙의 처음부터 모든 블록을 밟는다. 할당된 블록도 예외 없이. 빈 블록이 하나뿐이어도 그 앞에 할당된 블록이 만 개 있으면 만 번을 지나가야 한다. 얼마나 심한지 직접 세어봤다.

**실험 1. find_fit은 몇 개의 블록을 지나갈까**

`find_fit` 루프 안에 카운터를 하나 넣고, 작은 블록을 10000개 할당한 뒤 한 번 더 요청하는 코드를 작성해보자.

```c
static long visit_count;   /* find_fit 루프 안에서 visit_count++ */

int main(void) {
    mem_init();
    mm_init();

    for (int i = 0; i < 10000; i++) mm_malloc(16);

    visit_count = 0;
    mm_malloc(16);
    printf("visited: %ld\n", visit_count);
}
```

빈 블록 하나를 찾으려고 할당된 블록 만 개를 전부 지나갔다. implicit free list에서 탐색 비용은 **빈 블록 수가 아니라 전체 블록 수**에 비례한다. 할당이 쌓일수록 `malloc`이 느려지는 구조다. (시간복잡도로 나타내면 O(n)이다.)

## 빈 블록끼리만 이어보자

해결 방향은 단순하다. 빈 블록만 따로 연결해두면 탐색할 때 할당된 블록을 볼 일이 없다. 문제는 연결 정보, 즉 pointer를 어디에 둘 것인가다. 블록마다 pointer 칸을 따로 붙이면 모든 블록이 그만큼 커진다.

그런데 빈 블록에는 이미 아무도 쓰지 않는 공간이 있다. payload다. 사용자가 반납한 자리니 무엇을 적어도 상관없다. 여기에 이전/다음 빈 블록의 주소를 적어두면, 추가 메모리 없이 빈 블록끼리만 연결된 list가 생긴다. **빈 공간을 빈 공간 관리에 쓰는 것**이다.

```text {linenos=false}
      할당된 블록                          빈 블록
+-----------------------+          +-----------------------+
|   size       | 0 0 1  |  헤더     |   size       | 0 0 0  |  헤더
+-----------------------+ <- bp    +-----------------------+ <- bp
|                       |          |   pred                |  이전 빈 블록의 bp
|                       |          +-----------------------+
|       payload         |          |   succ                |  다음 빈 블록의 bp
|                       |          +-----------------------+
|                       |          |   (쓰지 않는 공간)       |
+-----------------------+          +-----------------------+
|   size       | 0 0 1  |  푸터     |   size       | 0 0 0  |  푸터
+-----------------------+          +-----------------------+
```

같은 자리가 할당 상태에서는 사용자 데이터, 해제 상태에서는 pointer 두 개가 된다. pointer가 들어 있는 건 블록이 비어 있는 동안뿐이라, 할당된 블록에는 추가 비용이 전혀 없다. 이렇게 빈 블록을 명시적인 pointer로 잇는 방식을 explicit free list라고 한다.

> [!NOTE]
> **왜 pointer가 두 개(pred, succ)나 필요할까?**
> 다음 블록만 가리키는 singly linked list로도 순회는 된다. 문제는 list 중간에서 블록을 빼낼 때다.
> coalesce로 이웃 빈 블록을 흡수하면 그 블록은 list에서 빠져야 하고, 빼내려면 앞 노드의 succ를 고쳐야 한다. singly linked라면 앞 노드를 찾으려고 list를 처음부터 다시 훑어야 한다. 탐색을 줄이려고 만든 구조에서 다시 탐색을 하는 셈이다. pred가 있으면 O(1)로 빠진다.

## 최소 블록 크기가 정해진다

빈 블록은 헤더, pred, succ, 푸터를 전부 담을 수 있어야 한다. 이 시리즈는 32bit 기준이라 pointer가 4바이트다.

```text {linenos=false}
헤더 4 + pred 4 + succ 4 + 푸터 4 = 16바이트
```

3편에서 `MINBLOCK`을 16으로 두고, `mm_malloc`에서 작은 요청을 `2 * DSIZE = 16`으로 올려 잡았던 것과 정확히 맞아떨어진다.

한 가지 짚고 넘어갈 점이 있다. 할당된 블록은 pred/succ를 쓰지 않는데도 16바이트 이상이어야 한다. 언젠가 `free`되는 순간 pred/succ를 담아야 하기 때문이다. malloc의 시간은 빨라지지만, 메모리 사용량은 증가한다. 이것이 trade-off다.

> [!NOTE]
> **64-bit에서는?**
> pointer가 8바이트라 4 + 8 + 8 + 4 = 24바이트, 이미 8의 배수이므로 최소 블록은 24가 된다.
> 32-bit 기준 코드를 64-bit로 그대로 빌드하면 16바이트 블록에 pred와 succ가 들어가지 않는다. succ가 푸터와 다음 블록의 헤더까지 덮어쓰고, 힙 전체가 조용히 망가진다.

## 두 개의 순서

explicit free list를 도입하면 힙 안에 순서가 두 개 생긴다.

```text {linenos=false}
주소 →
+--------+--------+--------+--------+--------+
| A free | B used | C free | D used | E free |
+--------+--------+--------+--------+--------+

free list:  free_listp → E → A → C → NULL
```

주소상으로는 A, C, E 순이지만 list에서는 E가 맨 앞이다. list의 순서는 블록이 **어디에 있는지**가 아니라 **언제, 어떤 규칙으로 list에 들어왔는지**로 정해진다.

두 순서는 쓰임새가 다르다.

- **물리적 순서** (헤더/푸터, `NEXT_BLKP`/`PREV_BLKP`): 바로 옆에 붙은 블록이 누구인가. `coalesce`가 합칠 이웃을 찾을 때 쓴다.
- **논리적 순서** (pred/succ): 빈 블록이 어디 어디 있는가. `find_fit`이 탐색할 때 쓴다.

list에서의 이웃은 메모리상 이웃이 아니다. 그래서 합칠 대상은 list로 찾을 수 없고, 3편과 똑같이 헤더/푸터로 찾는다. 헤더/푸터는 그대로 필요하고, pred/succ는 그 위에 한 겹 더해지는 구조다.

## 어디에 끼워 넣을까

블록이 비면 list에 넣어야 한다. 어디에 넣느냐에 따라 두 가지 정책이 있다.

**LIFO (Last In, First Out)**

해제된 블록을 list 맨 앞에 넣는다. head만 바꾸면 되니 삽입이 O(1)이다. 방금 해제한 블록이 다음 탐색에서 가장 먼저 발견되므로, 최근에 건드린 메모리를 다시 쓰게 된다는 장점도 있다. 대신 주소와 무관하게 섞이기 때문에 단편화가 더 생길 수 있다.

**Address-ordered**

list를 주소 순으로 유지한다. 삽입할 때 제자리를 찾아야 하니 O(n)이 든다. 대신 first fit과 조합하면 낮은 주소부터 채우게 되어, best fit에 가까운 메모리 이용률을 보인다고 알려져 있다.

이 시리즈에서는 LIFO로 구현한다. 삽입이 단순해서 coalesce와 list 조작의 관계를 먼저 명확하게 볼 수 있고, 정책을 바꾸고 싶으면 삽입 함수 하나만 고치면 되기 때문이다.

```text {linenos=false}
LIFO 삽입: C를 free 했을 때

전:   free_listp → E → A → NULL
후:   free_listp → C → E → A → NULL
```

## 무엇이 바뀌고, 무엇이 그대로인가

3편에서 `find_fit`은 찾기만, `place`는 배치만 하도록 역할을 나눠뒀다. 그 덕분에 explicit으로 바꿀 때 손댈 곳이 분명하다.

**그대로인 것**
- `PACK`, `GET`, `PUT`, `HDRP`, `FTRP`, `NEXT_BLKP`, `PREV_BLKP` 매크로
- `mm_malloc`의 흐름 (정렬 → `find_fit` → `place`, 없으면 `extend_heap`)
- `extend_heap`, `mm_free`

**바뀌는 것**
- 매크로 추가: 빈 블록의 pred/succ 칸을 읽고 쓰는 `PRED`, `SUCC`
- `find_fit`: `heap_listp`부터 힙 전체를 걷는 대신, `free_listp`부터 succ를 따라간다.
- `place`: 고른 블록을 list에서 뺀다. 쪼갰다면 남은 뒤쪽 블록을 list에 넣는다.
- `coalesce`: 흡수되는 이웃을 list에서 빼고, 합쳐진 블록(합칠 게 없으면 자기 자신)을 list에 넣는다.
- `mm_init`: `free_listp`를 초기화한다.
- `mm_realloc`: 매번 새로 할당하고 복사하는 대신, 지금 자리에서 해결할 수 있는지 먼저 확인한다. 뒤 블록이 비어 있으면 list에서 빼고 흡수한다.

여기에 list 조작 함수 두 개, `insert_node`와 `remove_node`가 새로 생긴다. `extend_heap`과 `mm_free`는 새로 생긴 빈 블록을 `coalesce`에 넘기기만 하므로, list에 넣는 일은 `coalesce`가 대신 처리해준다. 코드가 그대로인 이유다.

## explicit free list가 해결하지 않는 것

explicit free list가 줄이는 것은 **탐색 비용**이다. 탐색 대상이 전체 블록에서 빈 블록으로 줄어든다.

반면 list 구조 자체가 빈 공간을 이어 붙여주지는 않는다. 100바이트 빈 블록 두 개가 떨어져 있으면 list로 아무리 잘 엮어도 150바이트 요청은 들어가지 않는다. 삽입 정책이 어떤 블록이 선택되는지에 영향을 줄 수는 있지만, 떨어진 빈 블록을 하나로 만드는 건 여전히 `coalesce`뿐이다. 외부 단편화에 대한 대응은 달라지지 않는다.

이득의 크기도 상황에 따라 다르다. 실험 1처럼 할당된 블록이 압도적으로 많으면 효과가 크지만, 대부분의 블록이 비어 있다면 전체 블록 수와 빈 블록 수가 비슷해져 차이가 거의 없다.

## 그래서 무엇을 만들어야 하나

한 가지 생각해볼 거리가 남는다. 빈 블록의 payload에 주소를 적어둔다는 건, **해제된 메모리 안에 allocator가 믿고 따라가는 pointer가 들어 있다**는 뜻이다. 만약 프로그램이 이미 `free`한 포인터로 값을 쓴다면 무슨 일이 벌어질까? 이 질문은 나중에 heap exploitation을 다룰 때 다시 꺼낼 예정이다.

**다음 편에서는 `insert_free`, `remove_free`를 만들고 `find_fit`, `place`, `coalesce`를 explicit 버전으로 고칠 예정이다.**