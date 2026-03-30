# Plan: Admin Panel — Hotel AX 운영 관리 대시보드 구현 계획

> **요구사항 참조**: [admin_panel.md](../requirements/admin_panel.md)
> **우선순위**: P1
> **관련 하위 문서**:
> - [plan-admin-panel-2.md](./plan-admin-panel-2.md) — LangSmith 연동 / 부하 테스트 연동 상세

---

## 0. 사용할 Claude 스킬

각 구현 단계에서 아래 스킬을 적극 활용한다. 스킬 이름은 `/skill-name` 형태로 호출한다.

| 스킬 | 적용 단계 | 활용 목적 |
|------|-----------|-----------|
| `tdd-workflow` | 전 단계 공통 | 모든 신규 코드(Hotel API 추가 엔드포인트, Next.js Route Handler)는 테스트 먼저 작성. 80%+ 커버리지 목표 |
| `langsmith-trace` | Phase 1 — LangSmith 트레이스 조회 | LangSmith JS SDK 연동 패턴, `Client.listRuns()` 파라미터, 트레이스·run 계층 조회 방법 확인 |
| `langsmith-trace` | Phase 2 — LangSmith 데이터셋 평가 | `Client.listDatasets()`, `Client.listExamples()`, 실험 결과 조회 API 패턴 확인 |
| `github-actions-docs` | Phase 2 — CI/CD 부하 테스트 통합 | 부하 테스트 결과를 CI 파이프라인에서 Hotel API 웹훅으로 저장하는 워크플로 작성, `workflow_dispatch` 수동 트리거 설정 |
| `ruff-linting` | Hotel API 신규 엔드포인트 추가 시 | `app/api/routes/admin.py` 등 Python 코드 작성 후 ruff 오류 자동 감지·수정 |
| `clerk-nextjs-patterns` | Phase 1 — NextAuth 인증 구현 | Clerk의 Next.js 인증 패턴을 참조하여 NextAuth + Hotel API JWT 연동 구현. 미들웨어·세션 처리·보호 라우트 패턴 확인 |
| `shadcn` | 전 단계 UI 구현 | shadcn/ui 컴포넌트 사용법·커스터마이징 패턴 확인. 테이블·다이얼로그·Sheet·Badge 등 Admin Panel 핵심 컴포넌트 구현 시 참조 |
| `tanstack-start-best-practices` | 전 단계 데이터 페칭·라우팅 | TanStack Query 폴링(`refetchInterval`)·캐싱·낙관적 업데이트 패턴 확인. 헬스 카드 30초 폴링, 트레이스 목록 필터링, 문서 업로드 후 invalidateQueries 등 구현 시 참조 |
| `zustand` | 전 단계 클라이언트 상태 관리 | Zustand 스토어 정의·슬라이스 패턴 확인. 트레이스 날짜 필터, 문서 선택 상태, 사용자 테이블 정렬 기준 등 여러 컴포넌트에서 공유하는 UI 상태 관리 시 참조 |

### 스킬별 적용 시점 상세

#### `tdd-workflow` — 전 단계 공통
```
# Hotel API 신규 엔드포인트 (Python)
1. tests/test_admin_api.py 먼저 작성 (실패 확인)
2. app/api/routes/admin.py 구현
3. 테스트 통과 확인
4. pytest --cov=app --cov-fail-under=80

# Next.js Route Handler (TypeScript)
1. __tests__/api/traces.test.ts 먼저 작성
2. src/app/api/traces/route.ts 구현
3. jest 통과 확인
```

#### `langsmith-trace` — LangSmith JS SDK 연동
```
# 트레이스 조회 구현 전 참조
- Client.listRuns() 옵션 (isRoot, error, startTime, limit)
- 트레이스 계층 구조 (root run → child runs)
- 비용 필드 (total_cost, prompt_tokens, completion_tokens)

# 데이터셋 평가 구현 전 참조
- Client.listDatasets(), Client.readDataset()
- Client.listExamples(), Client.createExample()
- Client.listProjects() → 실험 목록
```

#### `github-actions-docs` — CI/CD 통합
```
# 부하 테스트 결과 저장 워크플로 작성 시 참조
- jobs.<job>.outputs 으로 테스트 결과 전달
- curl로 Hotel API 웹훅 POST
- workflow_dispatch inputs 으로 수동 트리거 파라미터 정의
- permissions: contents: read, id-token: write (OIDC 불필요 시 최소화)
```

#### `ruff-linting` — Python 코드 품질
```
# admin.py, audit CRUD 작성 후
python -m ruff check app/ tests/ --fix
# 커밋 전 pre-commit 훅이 자동 실행되지만, 작성 중에도 수시로 체크
```

---

## 1. 현재 상태

Admin Panel 관련 코드 없음. Hotel RAG API Server 백엔드는 완성되어 있으며, 이 계획은
**별도 Next.js 프론트엔드 리포지토리**를 새로 생성하는 것을 전제로 한다.

기존 인프라에서 재사용 가능한 것:
- JWT 인증 (Hotel RAG API Server 발급 토큰을 그대로 사용)
- Docker Compose (기존 `docker-compose.yml`에 서비스 추가)
- LangSmith API Key (`LANGSMITH_API_KEY` 환경 변수 이미 설정됨)

---

## 2. 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────────┐
│                    Admin Panel (별도 리포지토리)                   │
│                    Next.js 15 (App Router)                        │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Browser (Client Components)                                │ │
│  │  - shadcn/ui + Tailwind + Recharts                         │ │
│  │  - TanStack Query (폴링·캐싱)                               │ │
│  │  - Zustand (필터·선택 상태)                                 │ │
│  └──────────────────────┬──────────────────────────────────────┘ │
│                         │ fetch (Next.js Server Actions / Route)  │
│  ┌──────────────────────▼──────────────────────────────────────┐ │
│  │  Server Components / Route Handlers                         │ │
│  │  - LangSmith JS SDK (API Key 서버에서만 사용)               │ │
│  │  - Hotel API 호출 (JWT 전달)                                │ │
│  └──────────┬──────────────────────────┬────────────────────── ┘ │
└─────────────┼──────────────────────────┼─────────────────────────┘
              │                          │
              ▼                          ▼
  ┌──────────────────────┐   ┌──────────────────────────┐
  │  Hotel RAG API Server │   │  LangSmith Cloud API     │
  │  (FastAPI, port 8000) │   │  (langsmith.com)         │
  │  - /health            │   │  - traces                │
  │  - /metrics           │   │  - datasets              │
  │  - /api/v1/*          │   │  - experiments           │
  │  - /auth/*            │   └──────────────────────────┘
  │  - /admin/*  (신규)   │
  └──────────────────────┘
```

### 신규 백엔드 엔드포인트 (Hotel RAG API Server에 추가)

Admin Panel에서 호출할 API 중 기존에 없는 것들은 `app/api/routes/admin.py`로 추가한다.

| Method | Path | 설명 | 비고 |
|--------|------|------|------|
| GET | `/admin/users` | 사용자 목록 | 신규 |
| POST | `/admin/users` | 사용자 생성 | 신규 |
| PATCH | `/admin/users/{id}` | 역할·부서·활성 상태 변경 | 신규 |
| POST | `/admin/users/{id}/reset-password` | 비밀번호 강제 재설정 | 신규 |
| GET | `/admin/audit-logs` | 감사 로그 조회 | 신규 |
| GET | `/admin/load-test-results` | 부하 테스트 결과 이력 | 신규 |
| POST | `/admin/load-test-results` | CI에서 결과 저장 (CI→서버 웹훅) | 신규 |
| GET | `/api/v1/documents` | 문서 목록 | 기존 활용 |
| DELETE | `/api/v1/documents/{id}` | 문서 삭제/아카이브 | 기존 활용 |
| POST | `/api/v1/ingest` | 문서 업로드·인덱싱 | 기존 활용 |
| GET | `/health` | 컴포넌트 헬스 | 기존 활용 |
| GET | `/metrics` | API 메트릭 | 기존 활용 |

---

## 3. DB 스키마 (Hotel RAG API Server 측 추가)

```sql
-- 부하 테스트 결과 이력 (CI/CD 실행마다 저장)
CREATE TABLE load_test_results (
    id              INT      PRIMARY KEY AUTO_INCREMENT,
    ci_run_id       VARCHAR(100),                    -- GitHub Actions run ID
    branch          VARCHAR(200),
    commit_sha      VARCHAR(40),
    triggered_by    ENUM('ci', 'manual') NOT NULL DEFAULT 'ci',
    test_scenario   VARCHAR(100),                    -- 'api_load_50vu', 'chat_stress' 등
    -- 성능 지표
    p50_ms          INT,
    p95_ms          INT,
    p99_ms          INT,
    avg_ms          INT,
    max_ms          INT,
    error_rate_pct  DECIMAL(5,2),
    req_per_sec     DECIMAL(8,2),
    max_vus         INT,
    duration_sec    INT,
    -- 판정
    sla_passed      BOOLEAN NOT NULL DEFAULT TRUE,   -- p95 < 3000ms 기준
    raw_report_url  VARCHAR(500),                    -- CI artifact URL
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_created_at (created_at),
    INDEX idx_ci_run (ci_run_id)
);

-- 감사 로그 (관리 행위 기록)
CREATE TABLE audit_logs (
    id              INT      PRIMARY KEY AUTO_INCREMENT,
    actor_id        INT REFERENCES users(id),
    actor_email     VARCHAR(200),
    action          VARCHAR(100) NOT NULL,           -- 'user.create', 'user.deactivate', 'document.delete' 등
    target_type     VARCHAR(50),                     -- 'user', 'document', 'role'
    target_id       VARCHAR(100),
    before_value    JSON,
    after_value     JSON,
    ip_address      VARCHAR(45),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_actor (actor_id),
    INDEX idx_action (action),
    INDEX idx_created_at (created_at)
);
```

---

## 4. 구현 단계

### Phase 1 — 프로젝트 초기화 및 공통 인프라

#### 4-1. Next.js 프로젝트 생성

```bash
# 별도 리포지토리 생성
npx create-next-app@latest hotel-ax-admin \
  --typescript \
  --tailwind \
  --app \
  --src-dir \
  --import-alias "@/*"

cd hotel-ax-admin

# shadcn/ui 초기화
npx shadcn@latest init

# 핵심 컴포넌트 추가
npx shadcn@latest add button card table badge input label
npx shadcn@latest add dialog sheet tabs select toast
npx shadcn@latest add dropdown-menu avatar separator

# 의존성 추가
npm install @tanstack/react-query zustand recharts
npm install langsmith                     # LangSmith JS SDK
npm install next-auth                     # JWT 세션 관리
npm install axios                         # Hotel API 호출
npm install date-fns                      # 날짜 유틸
npm install react-dropzone                # 파일 업로드 UI
```

#### 4-2. 환경 변수 설정

```bash
# .env.local
HOTEL_API_URL=http://localhost:8000          # Docker 내부: http://api:8000
LANGSMITH_API_KEY=lsv2_pt_...               # 서버에서만 사용 (클라이언트 노출 금지)
LANGSMITH_PROJECT=hotel-ax
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=<랜덤 32자>
```

#### 4-3. Hotel API 클라이언트 (서버/클라이언트 공용)

```typescript
// src/lib/hotel-api.ts
import axios from "axios";

export const hotelApi = axios.create({
  baseURL: process.env.HOTEL_API_URL ?? "http://localhost:8000",
  timeout: 10_000,
});

// 서버 컴포넌트용: Authorization 헤더를 호출 측에서 주입
export function withAuth(token: string) {
  return {
    headers: { Authorization: `Bearer ${token}` },
  };
}
```

#### 4-4. JWT 인증 미들웨어 (NextAuth + Hotel API 토큰 재사용)

```typescript
// src/app/api/auth/[...nextauth]/route.ts
import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

const handler = NextAuth({
  providers: [
    CredentialsProvider({
      name: "Hotel AX",
      credentials: {
        email: { label: "이메일", type: "email" },
        password: { label: "비밀번호", type: "password" },
      },
      async authorize(credentials) {
        // Hotel RAG API Server의 /auth/login 호출
        const res = await fetch(`${process.env.HOTEL_API_URL}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: credentials?.email,
            password: credentials?.password,
          }),
        });

        if (!res.ok) return null;
        const data = await res.json();

        // admin 역할만 Admin Panel 접근 허용
        if (data.user?.role !== "admin") return null;

        return {
          id: data.user.id,
          email: data.user.email,
          name: data.user.full_name,
          role: data.user.role,
          accessToken: data.access_token,   // Hotel API JWT 보존
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.accessToken = (user as any).accessToken;
        token.role = (user as any).role;
      }
      return token;
    },
    async session({ session, token }) {
      (session as any).accessToken = token.accessToken;
      (session as any).role = token.role;
      return session;
    },
  },
  pages: { signIn: "/login" },
});

export { handler as GET, handler as POST };
```

```typescript
// src/middleware.ts — Admin Panel 전체 보호
import { withAuth } from "next-auth/middleware";

export default withAuth({
  pages: { signIn: "/login" },
});

export const config = {
  matcher: ["/((?!login|api/auth|_next/static|_next/image|favicon.ico).*)"],
};
```

---

### Phase 1 — 홈 대시보드 (ADMIN-F01~F05)

#### 4-5. 헬스 체크 폴링

```typescript
// src/app/api/health/route.ts — Hotel API 프록시 (API Key 숨김용)
import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { hotelApi, withAuth } from "@/lib/hotel-api";

export async function GET() {
  const session = await getServerSession();
  const { data } = await hotelApi.get(
    "/health",
    withAuth((session as any).accessToken)
  );
  return NextResponse.json(data);
}
```

```typescript
// src/components/dashboard/health-cards.tsx (Client Component)
"use client";
import { useQuery } from "@tanstack/react-query";

interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy";
  components: {
    database: { status: string };
    vector_store: { status: string };
    redis: { status: string };
  };
}

export function HealthCards() {
  const { data, isError } = useQuery<HealthStatus>({
    queryKey: ["health"],
    queryFn: () => fetch("/api/health").then((r) => r.json()),
    refetchInterval: 30_000,   // 30초 폴링 (ADMIN-NF02)
    staleTime: 25_000,
  });

  const components = [
    { key: "database", label: "MySQL" },
    { key: "vector_store", label: "ChromaDB" },
    { key: "redis", label: "Redis" },
  ] as const;

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <StatusCard
        label="API 서버"
        status={isError ? "unhealthy" : data?.status}
      />
      {components.map(({ key, label }) => (
        <StatusCard
          key={key}
          label={label}
          status={data?.components[key]?.status}
        />
      ))}
    </div>
  );
}

function StatusCard({
  label,
  status,
}: {
  label: string;
  status?: string;
}) {
  const color =
    status === "healthy" || status === "ok"
      ? "bg-green-100 text-green-700"
      : status === "degraded"
      ? "bg-yellow-100 text-yellow-700"
      : "bg-red-100 text-red-700";

  return (
    <div className={`rounded-lg p-4 ${color}`}>
      <p className="text-sm font-medium">{label}</p>
      <p className="text-xs mt-1 capitalize">{status ?? "확인 중..."}</p>
    </div>
  );
}
```

#### 4-6. 메트릭 KPI 카드 + 7일 추이 차트

```typescript
// src/app/(dashboard)/page.tsx (Server Component)
import { getServerSession } from "next-auth";
import { hotelApi, withAuth } from "@/lib/hotel-api";
import { HealthCards } from "@/components/dashboard/health-cards";
import { MetricsCards } from "@/components/dashboard/metrics-cards";
import { ApiCallChart } from "@/components/dashboard/api-call-chart";

export default async function DashboardPage() {
  const session = await getServerSession();
  const { data: metrics } = await hotelApi.get(
    "/metrics",
    withAuth((session as any).accessToken)
  );

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">운영 대시보드</h1>

      {/* 컴포넌트 헬스 (30초 폴링, Client Component) */}
      <HealthCards />

      {/* KPI 카드 (서버에서 초기 렌더링) */}
      <MetricsCards data={metrics} />

      {/* 7일 추이 차트 (Client Component) */}
      <ApiCallChart />
    </div>
  );
}
```

---

### Phase 1 — 문서 관리 (ADMIN-F10~F14)

#### 4-7. 문서 목록 + 업로드

```typescript
// src/app/(dashboard)/documents/page.tsx
import { getServerSession } from "next-auth";
import { hotelApi, withAuth } from "@/lib/hotel-api";
import { DocumentTable } from "@/components/documents/document-table";
import { UploadDocumentDialog } from "@/components/documents/upload-dialog";

export default async function DocumentsPage() {
  const session = await getServerSession();
  const { data } = await hotelApi.get(
    "/api/v1/documents",
    withAuth((session as any).accessToken)
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">문서 관리</h1>
        <UploadDocumentDialog />
      </div>
      <DocumentTable initialData={data.documents} />
    </div>
  );
}
```

```typescript
// src/components/documents/upload-dialog.tsx (Client Component)
"use client";
import { useState } from "react";
import { useDropzone } from "react-dropzone";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useQueryClient } from "@tanstack/react-query";

export function UploadDocumentDialog() {
  const [open, setOpen] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const { getRootProps, getInputProps, acceptedFiles } = useDropzone({
    accept: { "application/pdf": [], "text/plain": [], "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [] },
    maxSize: 50 * 1024 * 1024,   // 50MB (RAG-F06)
  });

  async function handleUpload(formData: FormData) {
    setProgress(0);
    const res = await fetch("/api/documents/upload", {
      method: "POST",
      body: formData,
    });
    if (res.ok) {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      setOpen(false);
    }
    setProgress(null);
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>문서 업로드</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>새 문서 업로드</DialogTitle>
          </DialogHeader>
          {/* 파일 드롭존 + 부서/버전 입력 폼 */}
          <div {...getRootProps()} className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer">
            <input {...getInputProps()} />
            <p className="text-sm text-muted-foreground">
              PDF, TXT, DOCX 파일을 드래그하거나 클릭하여 선택 (최대 50MB)
            </p>
          </div>
          {progress !== null && (
            <p className="text-sm">인덱싱 중... {progress}%</p>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
```

---

### Phase 1 — LangSmith 트레이스 조회 (ADMIN-F20~F23)

```typescript
// src/app/api/traces/route.ts — Server Route Handler (API Key 보호)
import { NextRequest, NextResponse } from "next/server";
import { Client } from "langsmith";

const langsmith = new Client({ apiKey: process.env.LANGSMITH_API_KEY });

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const limit = Number(searchParams.get("limit") ?? "20");
  const error = searchParams.get("error") === "true";
  const startTime = searchParams.get("start_time");
  const endTime = searchParams.get("end_time");

  const runs = langsmith.listRuns({
    projectName: process.env.LANGSMITH_PROJECT ?? "hotel-ax",
    isRoot: true,         // 루트 트레이스만 (ADMIN-F20)
    error,
    startTime: startTime ? new Date(startTime) : undefined,
    endTime: endTime ? new Date(endTime) : undefined,
    limit,
  });

  const results = [];
  for await (const run of runs) {
    results.push({
      id: run.id,
      name: run.name,
      status: run.status,
      startTime: run.start_time,
      endTime: run.end_time,
      latencyMs: run.end_time && run.start_time
        ? new Date(run.end_time).getTime() - new Date(run.start_time).getTime()
        : null,
      totalTokens: run.total_tokens,
      promptTokens: run.prompt_tokens,
      completionTokens: run.completion_tokens,
      totalCost: run.total_cost,
      error: run.error,
    });
  }

  return NextResponse.json({ traces: results });
}
```

```typescript
// src/app/(dashboard)/traces/page.tsx (Server Component 초기 데이터 + Client 필터)
import { TraceTable } from "@/components/traces/trace-table";

export default function TracesPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">LangSmith 트레이스</h1>
      <TraceTable />
    </div>
  );
}
```

```typescript
// src/components/traces/trace-table.tsx (Client Component)
"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";

export function TraceTable() {
  const [filter, setFilter] = useState({ error: false, startTime: "", endTime: "" });

  const { data, isLoading } = useQuery({
    queryKey: ["traces", filter],
    queryFn: () => {
      const params = new URLSearchParams();
      if (filter.error) params.set("error", "true");
      if (filter.startTime) params.set("start_time", filter.startTime);
      if (filter.endTime) params.set("end_time", filter.endTime);
      return fetch(`/api/traces?${params}`).then((r) => r.json());
    },
  });

  return (
    <div>
      {/* 필터 UI 생략 */}
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="py-2 text-left">이름</th>
            <th>상태</th>
            <th>응답 시간</th>
            <th>토큰</th>
            <th>비용 (USD)</th>
          </tr>
        </thead>
        <tbody>
          {data?.traces?.map((t: any) => (
            <tr key={t.id} className={`border-b ${t.error ? "bg-red-50" : ""}`}>
              <td className="py-2 font-mono text-xs">{t.name}</td>
              <td>
                <Badge variant={t.status === "success" ? "default" : "destructive"}>
                  {t.status}
                </Badge>
              </td>
              <td>{t.latencyMs ? `${(t.latencyMs / 1000).toFixed(2)}s` : "-"}</td>
              <td>{t.totalTokens ?? "-"}</td>
              <td>{t.totalCost ? `$${t.totalCost.toFixed(4)}` : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

---

### Phase 1 — 사용자 관리 (ADMIN-F30~F33)

```typescript
// src/app/(dashboard)/users/page.tsx
import { getServerSession } from "next-auth";
import { hotelApi, withAuth } from "@/lib/hotel-api";
import { UserTable } from "@/components/users/user-table";
import { CreateUserDialog } from "@/components/users/create-user-dialog";

export default async function UsersPage() {
  const session = await getServerSession();
  const { data } = await hotelApi.get(
    "/admin/users",
    withAuth((session as any).accessToken)
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">사용자 관리</h1>
        <CreateUserDialog />
      </div>
      <UserTable initialData={data.users} />
    </div>
  );
}
```

#### Hotel RAG API Server에 추가할 Admin API (app/api/routes/admin.py)

```python
# app/api/routes/admin.py
from fastapi import APIRouter, Depends, HTTPException
from app.auth.dependencies import require_admin
from app.database import crud

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
def list_users(current_user=Depends(require_admin)):
    return {"users": crud.get_all_users()}


@router.post("/users")
def create_user(data: UserCreate, current_user=Depends(require_admin)):
    user = crud.create_user(data)
    crud.create_audit_log(
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="user.create",
        target_type="user",
        target_id=str(user.id),
        after_value={"email": user.email, "role": user.role},
    )
    return user


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    data: UserUpdate,
    current_user=Depends(require_admin),
):
    before = crud.get_user(user_id)
    user = crud.update_user(user_id, data)
    crud.create_audit_log(
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="user.update",
        target_type="user",
        target_id=str(user_id),
        before_value={"role": before.role, "is_active": before.is_active},
        after_value={"role": user.role, "is_active": user.is_active},
    )
    return user


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, current_user=Depends(require_admin)):
    import secrets
    import string
    temp_pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    crud.set_user_password(user_id, temp_pw)
    crud.create_audit_log(
        actor_id=current_user.id,
        actor_email=current_user.email,
        action="user.reset_password",
        target_type="user",
        target_id=str(user_id),
    )
    # 이메일 발송 (알림 모듈 활용)
    user = crud.get_user(user_id)
    send_temp_password_email(user.email, temp_pw)
    return {"message": "임시 비밀번호가 이메일로 발송되었습니다."}


@router.get("/audit-logs")
def list_audit_logs(
    action: str = None,
    limit: int = 50,
    current_user=Depends(require_admin),
):
    return {"logs": crud.get_audit_logs(action=action, limit=limit)}
```

---

### Phase 2 — Docker Compose 통합

```yaml
# docker-compose.yml에 추가할 서비스
services:
  # ... 기존 api, celery_worker, mysql, redis 서비스 ...

  admin:
    build:
      context: ./hotel-ax-admin          # 별도 리포를 서브디렉터리로 체크아웃
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      HOTEL_API_URL: http://api:8000     # Docker 내부 네트워크
      LANGSMITH_API_KEY: ${LANGSMITH_API_KEY}
      LANGSMITH_PROJECT: ${LANGSMITH_PROJECT:-hotel-ax}
      NEXTAUTH_URL: http://localhost:3000
      NEXTAUTH_SECRET: ${ADMIN_NEXTAUTH_SECRET}
    depends_on:
      - api
    networks:
      - hotel_network
```

```dockerfile
# hotel-ax-admin/Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```

---

### Phase 2 — 대화 분석 (ADMIN-F40~F42)

Hotel RAG API Server에 집계 엔드포인트 추가:

```python
# app/api/routes/admin.py (추가)

@router.get("/analytics/chat")
def get_chat_analytics(
    period: str = "weekly",   # weekly | monthly
    current_user=Depends(require_admin),
):
    """채팅 세션·질문·거절 수 집계"""
    stats = crud.get_chat_stats(period=period)
    rejected = crud.get_rejected_questions(limit=50)
    return {
        "summary": stats,
        "rejected_questions": rejected,
    }
```

---

## 5. 파일 구조 (Admin Panel 리포지토리)

```
hotel-ax-admin/
├── Dockerfile
├── next.config.ts
├── package.json
├── .env.local.example
├── src/
│   ├── app/
│   │   ├── (auth)/
│   │   │   └── login/
│   │   │       └── page.tsx              # 로그인 페이지
│   │   ├── (dashboard)/
│   │   │   ├── layout.tsx                # 사이드바 + 헤더 레이아웃
│   │   │   ├── page.tsx                  # 홈 대시보드
│   │   │   ├── documents/
│   │   │   │   └── page.tsx
│   │   │   ├── traces/
│   │   │   │   └── page.tsx
│   │   │   ├── users/
│   │   │   │   └── page.tsx
│   │   │   ├── analytics/                # Phase 2
│   │   │   ├── evaluations/              # Phase 2
│   │   │   ├── operations/               # Phase 2
│   │   │   └── load-tests/               # Phase 2
│   │   └── api/
│   │       ├── auth/[...nextauth]/       # NextAuth 핸들러
│   │       │   └── route.ts
│   │       ├── health/
│   │       │   └── route.ts              # Hotel API 프록시
│   │       ├── traces/
│   │       │   └── route.ts              # LangSmith SDK 호출
│   │       └── documents/
│   │           └── upload/
│   │               └── route.ts
│   ├── components/
│   │   ├── layout/
│   │   │   ├── sidebar.tsx
│   │   │   └── header.tsx
│   │   ├── dashboard/
│   │   │   ├── health-cards.tsx
│   │   │   ├── metrics-cards.tsx
│   │   │   └── api-call-chart.tsx
│   │   ├── documents/
│   │   │   ├── document-table.tsx
│   │   │   └── upload-dialog.tsx
│   │   ├── traces/
│   │   │   ├── trace-table.tsx
│   │   │   └── trace-detail-panel.tsx
│   │   └── users/
│   │       ├── user-table.tsx
│   │       └── create-user-dialog.tsx
│   └── lib/
│       ├── hotel-api.ts                  # Hotel API axios 클라이언트
│       └── query-client.ts              # TanStack Query 설정
```

---

## 6. 구현 체크리스트

### Phase 1 — MVP (핵심 기능)

#### 프로젝트 기반
- [ ] Next.js 15 프로젝트 생성 및 shadcn/ui 설정
- [ ] NextAuth + Hotel API JWT 연동 (Admin 역할 전용 접근)
- [ ] 사이드바 레이아웃 (페이지 링크 + 로그아웃)
- [ ] Docker Compose에 admin 서비스 추가
- [ ] `.env.example` 작성

#### 홈 대시보드
- [ ] 헬스 카드 (30초 폴링, ADMIN-F01~F02)
- [ ] KPI 카드 — 호출 수·응답 시간·오류율 (ADMIN-F03)
- [ ] 토큰 사용량·추정 비용 카드 (ADMIN-F04)
- [ ] 7일 API 호출 추이 라인 차트 (ADMIN-F05)

#### 문서 관리
- [ ] 문서 목록 테이블 + 필터 (ADMIN-F10)
- [ ] 파일 업로드 모달 (드롭존 + 부서/버전 입력) (ADMIN-F11)
- [ ] 아카이브·삭제 기능 (ADMIN-F12)
- [ ] 재인덱싱 트리거 버튼 (ADMIN-F13)
- [ ] 인덱싱 오류 배지 표시 (ADMIN-F14)

#### LangSmith 트레이스
- [ ] Route Handler에서 LangSmith JS SDK 연동 (API Key 서버 보호)
- [ ] 트레이스 목록 테이블 + 날짜·상태 필터 (ADMIN-F20)
- [ ] 트레이스 상세 슬라이드오버 — run 계층 트리 (ADMIN-F21)
- [ ] 오류 트레이스 행 강조 (ADMIN-F22)
- [ ] 토큰·비용 컬럼 표시 (ADMIN-F23)

#### 사용자 관리
- [ ] Hotel API에 `/admin/users`, `/admin/audit-logs` 엔드포인트 추가
- [ ] `audit_logs` 테이블 마이그레이션
- [ ] 사용자 목록 테이블 (ADMIN-F30)
- [ ] 사용자 생성 모달 (ADMIN-F31)
- [ ] 역할·비활성화·감사 로그 연동 (ADMIN-F32)
- [ ] 비밀번호 강제 재설정 (ADMIN-F33)

### Phase 2 — 확장 기능

#### 대화 분석
- [ ] 세션·거절 수 집계 API 추가 (Hotel API)
- [ ] 주간·월간 집계 차트 (ADMIN-F40)
- [ ] 미응답 질문 목록 (ADMIN-F41)
- [ ] 키워드 빈도 차트 (ADMIN-F42)

#### LangSmith 평가
- [ ] 데이터셋 목록 + 예제 CRUD (ADMIN-F50)
- [ ] 실험 결과 차트 (ADMIN-F51)
- [ ] 트레이스 딥링크 (ADMIN-F52)

#### 운영 KPI
- [ ] 워크오더 분류 정확도 차트 (ADMIN-F60)
- [ ] 처리 시간 분포 바 차트 (ADMIN-F61)
- [ ] AI 요율 권고 vs 실제 비교 차트 (ADMIN-F70)
- [ ] MAPE 월별 추이 + 목표 기준선 (ADMIN-F71)

#### 부하 테스트
- [ ] `load_test_results` 테이블 마이그레이션 (Hotel API)
- [ ] CI/CD 결과 저장 웹훅 엔드포인트 추가
- [ ] 부하 테스트 이력 목록 (ADMIN-F80)
- [ ] p95 추이 차트 + SLA 기준선 (ADMIN-F81)
- [ ] 수동 트리거 버튼 → CI 웹훅 호출 (ADMIN-F82)
