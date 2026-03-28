# Plan: Work Order Automation — 모바일 UI / 알림 시스템 상세

> **상위 문서**: [plan-work-order-automation.md](./plan-work-order-automation.md)
> **내용**: 모바일 인터페이스, 오프라인 지원, 알림 채널 상세, Guest QR 신고

---

## 1. 모바일 인터페이스 설계

### 1-1. 담당자용 모바일 뷰 (Next.js PWA)

Work Order 앱은 별도 네이티브 앱 없이 **PWA(Progressive Web App)** 로 구현. 홈 화면 추가 지원, 오프라인 동작 지원.

```
/mobile/work-orders           # 내 Work Order 목록 (긴급도 정렬)
/mobile/work-orders/[id]      # 상세 + 상태 업데이트
/mobile/work-orders/new       # 신고 접수 (직원용)
/mobile/scan                  # QR 스캔 → 객실 정보 자동 입력
```

### 1-2. 담당자 Work Order 목록 UI

```
┌────────────────────────────────────┐
│ 내 Work Order (오늘)          [전체]│
├────────────────────────────────────┤
│ 🔴 CRITICAL  WO-2026-03001         │
│    503호 - 욕실 누수                │
│    배정: 09:15 | 완료기한: 11:15   │
│    [수락] [거절]                    │
├────────────────────────────────────┤
│ 🟠 HIGH      WO-2026-03002         │
│    VIP 601호 - 에어컨 불작동        │
│    배정: 09:20 | 완료기한: 13:20   │
│    ● 진행중                         │
│    [완료 처리]                      │
├────────────────────────────────────┤
│ 🟡 MEDIUM    WO-2026-03005         │
│    205호 - TV 화면 이상             │
│    배정: 09:45 | 완료기한: 18:00   │
│    [시작]                           │
└────────────────────────────────────┘
```

### 1-3. 완료 처리 폼 UI

```
┌────────────────────────────────────┐
│ WO-2026-03001 완료 처리            │
├────────────────────────────────────┤
│ 처리 내용 (필수)                   │
│ ┌──────────────────────────────┐  │
│ │ 욕실 수도꼭지 패킹 교체.      │  │
│ │ 파이프 연결부 실리콘 재시공.  │  │
│ └──────────────────────────────┘  │
│                                    │
│ 사용 부품/재료                     │
│ [+ 부품 추가]                      │
│  ├ 수도꼭지 패킹   수량: [1]  [×] │
│  └ 실리콘         수량: [1]  [×] │
│                                    │
│ 소요 시간: [45] 분                 │
│                                    │
│ 완료 사진 (선택)                   │
│ [📷 카메라] [🖼 갤러리]            │
│                                    │
│ 외부 업체 호출?                    │
│ ○ 내부 처리  ● 외부 업체           │
│ 업체명: [              ]           │
│                                    │
│         [완료 제출]                 │
└────────────────────────────────────┘
```

---

## 2. 오프라인 지원 (WO-NF03)

### 2-1. Service Worker 전략

```javascript
// public/sw.js (Service Worker)

const CACHE_NAME = 'hotel-wo-v1'
const OFFLINE_QUEUE_KEY = 'offline_work_orders'

// 캐시할 정적 자원
const STATIC_ASSETS = [
  '/',
  '/mobile/work-orders',
  '/offline.html',
  // CSS, JS 번들
]

// 설치 시 정적 자원 캐시
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  )
})

// 네트워크 요청 처리
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)

  // API 요청: Network First (오프라인 시 큐에 저장)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request.clone())
        .catch(() => {
          // 오프라인 상태: POST 요청은 큐에 저장
          if (event.request.method === 'POST') {
            return event.request.json().then(body => {
              return enqueueOfflineRequest({
                url: url.pathname,
                method: 'POST',
                body,
                timestamp: Date.now()
              })
            })
          }
          return new Response('{"error": "offline"}', { status: 503 })
        })
    )
    return
  }

  // 정적 자원: Cache First
  event.respondWith(
    caches.match(event.request).then(cached => cached || fetch(event.request))
  )
})

// 온라인 복구 시 큐에 저장된 요청 재전송
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-work-orders') {
    event.waitUntil(syncOfflineQueue())
  }
})

async function syncOfflineQueue() {
  const queue = JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || '[]')
  const remaining = []

  for (const req of queue) {
    try {
      await fetch(req.url, {
        method: req.method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body)
      })
    } catch {
      remaining.push(req)  // 여전히 실패하면 재큐
    }
  }

  localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(remaining))
}
```

### 2-2. IndexedDB를 활용한 오프라인 저장

```javascript
// lib/offlineStorage.ts

import { openDB } from 'idb'

const DB_NAME = 'hotel-work-orders'
const DB_VERSION = 1

export async function getOfflineDB() {
  return openDB(DB_NAME, DB_VERSION, {
    upgrade(db) {
      // 오프라인 중 생성된 Work Order 임시 저장
      const store = db.createObjectStore('pending_work_orders', {
        keyPath: 'localId',
        autoIncrement: true
      })
      store.createIndex('timestamp', 'timestamp')

      // 내 Work Order 목록 캐시 (오프라인 열람용)
      db.createObjectStore('cached_work_orders', { keyPath: 'id' })
    }
  })
}

export async function savePendingWorkOrder(data: object) {
  const db = await getOfflineDB()
  const localId = await db.add('pending_work_orders', {
    ...data,
    timestamp: Date.now(),
    synced: false
  })
  // Background Sync 등록
  if ('serviceWorker' in navigator && 'SyncManager' in window) {
    const reg = await navigator.serviceWorker.ready
    await reg.sync.register('sync-work-orders')
  }
  return localId
}

export async function cacheWorkOrders(workOrders: object[]) {
  const db = await getOfflineDB()
  const tx = db.transaction('cached_work_orders', 'readwrite')
  await Promise.all(workOrders.map(wo => tx.store.put(wo)))
  await tx.done
}
```

---

## 3. 알림 시스템 상세 (SYS-F10~13)

### 3-1. 알림 채널별 구현

#### 푸시 알림 (Web Push API)

```python
# app/notifications/push.py

from pywebpush import webpush, WebPushException
import json

class WebPushNotifier:
    def __init__(self):
        self.vapid_private_key = settings.vapid_private_key
        self.vapid_claims = {"sub": "mailto:admin@hotel.com"}

    def send(self, subscription: dict, title: str, message: str, action_url: str = None):
        payload = json.dumps({
            "title": title,
            "body": message,
            "icon": "/icon-192.png",
            "badge": "/badge-72.png",
            "data": {"url": action_url or "/"},
            "tag": "hotel-wo",          # 동일 태그는 이전 알림 교체
            "requireInteraction": True  # Critical 알림은 사용자 액션까지 유지
        })

        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=self.vapid_private_key,
                vapid_claims=self.vapid_claims
            )
        except WebPushException as e:
            if "410" in str(e):  # 구독 만료 → DB에서 삭제
                delete_push_subscription(subscription["endpoint"])
            else:
                raise
```

#### 이메일 알림 (SMTP)

```python
# app/notifications/email.py

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from tenacity import retry, stop_after_attempt, wait_exponential

class EmailNotifier:
    def __init__(self):
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=30))
    def send(self, to: str, subject: str, html_body: str):
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"호텔 운영 시스템 <{self.smtp_user}>"
        msg['To'] = to

        # HTML 본문
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.smtp_user, to, msg.as_string())

    def send_work_order_assigned(self, to: str, work_order: dict):
        severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
        html = f"""
<html><body>
<h2>{severity_emoji.get(work_order['severity'], '⚪')} Work Order 배정 알림</h2>
<table border="1" cellpadding="8" style="border-collapse:collapse">
  <tr><th>번호</th><td>{work_order['wo_number']}</td></tr>
  <tr><th>객실</th><td>{work_order.get('room_no', '미지정')}</td></tr>
  <tr><th>유형</th><td>{work_order['category']}</td></tr>
  <tr><th>긴급도</th><td>{work_order['severity'].upper()}</td></tr>
  <tr><th>내용</th><td>{work_order['description']}</td></tr>
  <tr><th>완료 기한</th><td>{work_order['sla_deadline']}</td></tr>
</table>
<br>
<a href="https://hotel-app/mobile/work-orders/{work_order['id']}"
   style="background:#2563eb;color:white;padding:12px 24px;text-decoration:none;border-radius:6px">
  Work Order 확인하기
</a>
</body></html>
"""
        self.send(to=to, subject=f"[{work_order['severity'].upper()}] Work Order 배정 - {work_order['wo_number']}", html_body=html)
```

### 3-2. 알림 이력 저장

```sql
CREATE TABLE notification_logs (
    id          INT      PRIMARY KEY AUTO_INCREMENT,
    user_id     INT      REFERENCES users(id),
    channel     ENUM('email','push','sms') NOT NULL,
    title       VARCHAR(200) NOT NULL,
    message     TEXT,
    related_type VARCHAR(50),     -- 'work_order', 'sop', 'inspection'
    related_id  VARCHAR(36),
    status      ENUM('sent','failed','retry') NOT NULL DEFAULT 'sent',
    error_message TEXT,
    attempt_count INT NOT NULL DEFAULT 1,
    sent_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_related (related_type, related_id)
);
```

---

## 4. Guest QR 신고 시스템 (WO-F04)

### 4-1. QR 코드 생성

각 객실마다 고유한 신고 URL이 포함된 QR 코드 생성. URL에 객실 번호와 서명 토큰 포함.

```python
# app/api/routes/guest.py

import qrcode
import hashlib
import hmac
from io import BytesIO

def generate_room_qr(room_no: str) -> bytes:
    """객실용 신고 QR 코드 생성"""
    token = hmac.new(
        settings.qr_secret.encode(),
        f"room:{room_no}".encode(),
        hashlib.sha256
    ).hexdigest()[:16]

    url = f"https://hotel-app/guest/report?room={room_no}&t={token}"

    img = qrcode.make(url, error_correction=qrcode.constants.ERROR_CORRECT_M)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()

# Guest 신고 엔드포인트 (인증 불필요)
@router.post("/guest/work-orders")
async def guest_report(
    room_no: str,
    token: str,
    description: str,
    guest_name: str = None,
    guest_contact: str = None
):
    # 토큰 검증
    expected_token = hmac.new(
        settings.qr_secret.encode(),
        f"room:{room_no}".encode(),
        hashlib.sha256
    ).hexdigest()[:16]

    if not hmac.compare_digest(token, expected_token):
        raise HTTPException(status_code=401, detail="유효하지 않은 QR 코드")

    # Work Order 생성 (신고자는 게스트 시스템 계정)
    wo = create_work_order({
        "room_no": room_no,
        "description": f"[투숙객 신고] {description}",
        "reported_by": GUEST_SYSTEM_USER_ID,  # 시스템 계정
        "guest_name": guest_name,
        "guest_contact": guest_contact,
        "source": "guest_qr"
    })

    return {"wo_number": wo["wo_number"], "message": "신고가 접수되었습니다. 빠르게 조치하겠습니다."}
```

### 4-2. QR 코드 관리 API

```
GET  /api/v1/rooms/{room_no}/qr      # 객실 QR 코드 이미지 다운로드
POST /api/v1/rooms/qr/bulk           # 전체 객실 QR 코드 ZIP 다운로드
```

---

## 5. 실시간 대시보드 (WebSocket)

```python
# app/api/routes/dashboard.py

from fastapi import WebSocket, WebSocketDisconnect
from typing import List

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    async def broadcast_work_order_update(self, work_order: dict):
        """모든 연결된 관리자 화면에 실시간 업데이트 전송"""
        message = {
            "type": "work_order_update",
            "data": work_order
        }
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                self.active_connections.remove(connection)

manager = ConnectionManager()

@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket, token: str):
    # JWT 검증
    verify_token(token)
    await manager.connect(websocket)
    try:
        while True:
            # 클라이언트로부터 heartbeat 수신
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.active_connections.remove(websocket)
```

```typescript
// 프런트엔드에서 WebSocket 구독
// hooks/useWorkOrderDashboard.ts

export function useWorkOrderDashboard() {
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])

  useEffect(() => {
    const token = getAccessToken()
    const ws = new WebSocket(`ws://localhost:8000/api/v1/ws/dashboard?token=${token}`)

    ws.onmessage = (event) => {
      const { type, data } = JSON.parse(event.data)
      if (type === 'work_order_update') {
        setWorkOrders(prev =>
          prev.map(wo => wo.id === data.id ? data : wo)
              .concat(prev.some(wo => wo.id === data.id) ? [] : [data])
        )
      }
    }

    // Heartbeat
    const heartbeat = setInterval(() => ws.send('ping'), 30000)

    return () => {
      clearInterval(heartbeat)
      ws.close()
    }
  }, [])

  return { workOrders }
}
```

---

## 6. 추가 의존성

```
# requirements.txt 추가
pywebpush>=2.0.0       # Web Push 알림
qrcode>=7.4.2          # QR 코드 생성
Pillow>=10.0.0         # QR 이미지 처리

# Next.js 추가 패키지
npm install idb        # IndexedDB 래퍼
npm install workbox-*  # Service Worker 유틸리티
```

---

## 7. next.config.ts PWA 설정

```typescript
// next.config.ts
import withPWA from 'next-pwa'

const config = withPWA({
  dest: 'public',
  disable: process.env.NODE_ENV === 'development',
  register: true,
  skipWaiting: true,
  runtimeCaching: [
    {
      urlPattern: /^https:\/\/.*\/api\/v1\/work-orders/,
      handler: 'NetworkFirst',
      options: {
        cacheName: 'api-cache',
        expiration: { maxAgeSeconds: 60 * 60 },  // 1시간
        networkTimeoutSeconds: 5
      }
    }
  ]
})({
  // next.js 설정
})

export default config
```
