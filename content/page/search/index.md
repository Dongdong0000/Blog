---
title: "검색"
slug: "search"
layout: "search"
url: "/search/"
# Stack 검색은 이 페이지의 JSON 출력을 색인으로 씁니다 — outputs 를 빼면 검색이 동작하지 않습니다.
# 또한 이 파일은 반드시 content/page/ 아래에 있어야 합니다 (테마 템플릿이 layouts/page/search.* 라서).
outputs:
    - html
    - json
menu:
    main:
        weight: 40
        params:
            icon: search
---
