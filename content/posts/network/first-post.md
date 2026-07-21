---
title: "첫 글 - 블로그 기능 테스트"
date: 2026-07-14
draft: false
tags: ["테스트"]
description: "Mermaid 다이어그램, 코드 하이라이팅, 목차 테스트"
---
## 다이어그램

```mermaid
sequenceDiagram
    participant C as 클라이언트
    participant S as 서버
    C->>S: SYN
    S->>C: SYN-ACK
    C->>S: ACK
    Note over C,S: 3-way handshake 완료
    C->>S: HTTP 요청
    S->>C: HTTP 응답
```
```mermaid
stateDiagram-v2
    [*] --> CLOSED
    CLOSED --> LISTEN: 서버 소켓 열기
    LISTEN --> SYN_RCVD: SYN 수신
    SYN_RCVD --> ESTABLISHED: ACK 수신
    ESTABLISHED --> CLOSED: 연결 종료
```

## 코드 하이라이팅

```c
#include <stdio.h>
#include <string.h>

// 간단한 버퍼 예제
int main(void) {
    char buf[16];
    strncpy(buf, "hello, world", sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    printf("%s\n", buf);
    return 0;
}
```

```bash
# 열려 있는 포트 확인
ss -tuln

# 특정 프로세스가 연 파일 확인
lsof -p <PID>
```

## 인라인 요소들

문장 중간에 `malloc()` 같은 인라인 코드도 쓸 수 있고, **굵게**나 *기울임*도 됩니다. [링크](https://gohugo.io)도 이렇게 걸립니다.

> 인용문은 이렇게 표시됩니다. 공부하다 인상 깊었던 문장을 남길 때 쓰면 좋겠습니다.