# Plan: RAG Assistant — 프런트엔드 구현 계획

> **상위 문서**: [plan-rag-assistant.md](./plan-rag-assistant.md)
> **프로젝트 경로**: `C:\Users\broke\projects\hotel-rag`
> **기술 스택**: Next.js 14 (App Router), TypeScript, Tailwind CSS

---

## 1. 현재 상태

`hotel-rag` 프로젝트는 Next.js 초기 스켈레톤 상태. `src/app/page.tsx`와 `layout.tsx`만 존재하며 실제 UI는 미구현.

---

## 2. 전체 페이지 구조

```
/                      → 리다이렉트 → /chat 또는 /login
/login                 → 로그인 페이지
/chat                  → 메인 채팅 인터페이스 (인증 필요)
/chat/[session_id]     → 특정 세션 채팅
/documents             → 문서 목록 관리 (Manager+)
/documents/upload      → 문서 업로드 (Manager+)
/documents/[doc_id]    → 문서 상세 + 버전 이력
/admin                 → 관리자 대시보드 (Admin)
/admin/users           → 사용자 관리
```

---

## 3. 컴포넌트 구조

```
src/
├── app/
│   ├── layout.tsx                    # 루트 레이아웃 (AuthProvider 감싸기)
│   ├── page.tsx                      # / → 리다이렉트
│   ├── login/
│   │   └── page.tsx                  # 로그인 폼
│   ├── chat/
│   │   ├── layout.tsx                # 사이드바 + 채팅 영역 레이아웃
│   │   ├── page.tsx                  # 새 채팅 시작
│   │   └── [session_id]/
│   │       └── page.tsx              # 기존 세션 재개
│   ├── documents/
│   │   ├── page.tsx                  # 문서 목록
│   │   ├── upload/page.tsx           # 업로드
│   │   └── [doc_id]/page.tsx         # 문서 상세
│   └── admin/
│       ├── page.tsx                  # 관리자 대시보드
│       └── users/page.tsx            # 사용자 관리
│
├── components/
│   ├── auth/
│   │   ├── LoginForm.tsx
│   │   └── AuthGuard.tsx             # 인증 미완료 시 /login 리다이렉트
│   ├── chat/
│   │   ├── ChatWindow.tsx            # 메시지 목록 + 스크롤
│   │   ├── MessageBubble.tsx         # 개별 메시지 (human/ai 구분)
│   │   ├── SourcePanel.tsx           # 출처 문서 패널 (펼침/접힘)
│   │   ├── ChatInput.tsx             # 입력창 + 전송 버튼
│   │   └── SessionSidebar.tsx        # 세션 이력 사이드바
│   ├── documents/
│   │   ├── DocumentList.tsx          # 문서 목록 테이블
│   │   ├── DocumentUploadForm.tsx    # 드래그앤드롭 업로드
│   │   ├── VersionHistory.tsx        # 버전 이력 타임라인
│   │   └── AcknowledgeButton.tsx     # SOP 확인 버튼
│   └── common/
│       ├── Navbar.tsx
│       ├── Sidebar.tsx
│       ├── LoadingSpinner.tsx
│       └── ErrorBoundary.tsx
│
├── hooks/
│   ├── useChat.ts                    # 채팅 상태 + API 호출
│   ├── useAuth.ts                    # 인증 상태 관리
│   └── useDocuments.ts               # 문서 CRUD
│
├── lib/
│   ├── api.ts                        # Axios 인스턴스 + 인터셉터
│   ├── auth.ts                       # 토큰 저장/조회 (httpOnly 쿠키)
│   └── types.ts                      # TypeScript 타입 정의
│
└── middleware.ts                     # Next.js 미들웨어 (라우트 보호)
```

---

## 4. 핵심 컴포넌트 상세 설계

### 4-1. ChatWindow + 스트리밍 지원

백엔드가 스트리밍을 지원하면 SSE(Server-Sent Events) 방식으로 토큰 단위 수신. 미지원 시 일반 POST → 응답 대기.

```typescript
// hooks/useChat.ts

interface Message {
  id: string
  role: 'human' | 'ai'
  content: string
  sourceDocuments: SourceDocument[]
  createdAt: Date
}

interface SourceDocument {
  source: string
  page?: number
  section?: string
  chunkPreview: string
}

export function useChat(sessionId?: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [currentSessionId, setCurrentSessionId] = useState(sessionId)

  const sendMessage = async (text: string) => {
    // 1. 사용자 메시지 즉시 추가
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'human',
      content: text,
      sourceDocuments: [],
      createdAt: new Date()
    }
    setMessages(prev => [...prev, userMsg])
    setIsLoading(true)

    // 2. API 호출
    const response = await api.post('/chat', {
      message: text,
      session_id: currentSessionId
    })

    // 3. AI 응답 추가
    const aiMsg: Message = {
      id: crypto.randomUUID(),
      role: 'ai',
      content: response.data.answer,
      sourceDocuments: response.data.source_documents,
      createdAt: new Date()
    }
    setMessages(prev => [...prev, aiMsg])
    setCurrentSessionId(response.data.session_id)
    setIsLoading(false)
  }

  return { messages, isLoading, sendMessage, sessionId: currentSessionId }
}
```

### 4-2. MessageBubble + SourcePanel

```typescript
// components/chat/MessageBubble.tsx

export function MessageBubble({ message }: { message: Message }) {
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const isAI = message.role === 'ai'

  return (
    <div className={`flex ${isAI ? 'justify-start' : 'justify-end'} mb-4`}>
      <div className={`max-w-[75%] ${isAI ? 'bg-white border' : 'bg-blue-600 text-white'} rounded-2xl px-4 py-3 shadow-sm`}>
        {/* 메시지 내용 (마크다운 렌더링) */}
        <ReactMarkdown>{message.content}</ReactMarkdown>

        {/* 출처 문서 (AI 메시지만) */}
        {isAI && message.sourceDocuments.length > 0 && (
          <div className="mt-3 border-t pt-2">
            <button
              onClick={() => setSourcesOpen(!sourcesOpen)}
              className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
            >
              <FileIcon size={12} />
              출처 {message.sourceDocuments.length}개
              {sourcesOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
            {sourcesOpen && (
              <SourcePanel sources={message.sourceDocuments} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// components/chat/SourcePanel.tsx

export function SourcePanel({ sources }: { sources: SourceDocument[] }) {
  return (
    <div className="mt-2 space-y-2">
      {sources.map((src, i) => (
        <div key={i} className="bg-gray-50 rounded-lg p-2 text-xs">
          <div className="font-medium text-gray-700 flex items-center gap-1">
            <DocumentIcon size={10} />
            {src.source}
            {src.page && <span className="text-gray-400">p.{src.page}</span>}
          </div>
          {src.section && (
            <div className="text-gray-500 mt-0.5">{src.section}</div>
          )}
          <div className="text-gray-600 mt-1 italic">"{src.chunkPreview}..."</div>
        </div>
      ))}
    </div>
  )
}
```

### 4-3. DocumentUploadForm (드래그앤드롭)

```typescript
// components/documents/DocumentUploadForm.tsx

export function DocumentUploadForm() {
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const f = acceptedFiles[0]
    if (!['application/pdf', 'text/plain', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'].includes(f.type)) {
      alert('PDF, TXT, DOCX 파일만 업로드 가능합니다')
      return
    }
    setFile(f)
  }, [])

  const handleSubmit = async (data: FormData) => {
    setUploading(true)
    const formData = new FormData()
    formData.append('file', file!)
    formData.append('title', data.get('title') as string)
    formData.append('department_id', data.get('department_id') as string)
    formData.append('tags', data.get('tags') as string)
    formData.append('change_summary', data.get('change_summary') as string)

    const result = await api.post('/documents', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => setProgress(Math.round(e.loaded * 100 / e.total!))
    })

    // 완료 후 인덱싱 결과 표시
    alert(`업로드 완료: ${result.data.indexed_chunks}개 청크 인덱싱됨 (${result.data.duration_ms}ms)`)
    setUploading(false)
  }

  return (
    <form onSubmit={handleSubmit}>
      {/* 드래그앤드롭 영역 */}
      <Dropzone onDrop={onDrop} accept={{ 'application/pdf': [], 'text/plain': [], '...': [] }}>
        {({ getRootProps, getInputProps, isDragActive }) => (
          <div {...getRootProps()} className={`border-2 border-dashed rounded-xl p-8 text-center ${isDragActive ? 'border-blue-400 bg-blue-50' : 'border-gray-300'}`}>
            <input {...getInputProps()} />
            {file ? <p className="font-medium">{file.name} ({(file.size / 1024 / 1024).toFixed(1)}MB)</p>
                  : <p className="text-gray-500">파일을 드래그하거나 클릭하여 선택하세요<br/><span className="text-sm">PDF, TXT, DOCX (최대 50MB)</span></p>}
          </div>
        )}
      </Dropzone>

      {/* 메타데이터 입력 */}
      <input name="title" placeholder="문서 제목" required className="..." />
      <select name="department_id" required className="...">
        <option value="front_office">프런트 오피스</option>
        {/* ... */}
      </select>
      <input name="tags" placeholder="태그 (쉼표 구분)" className="..." />
      <textarea name="change_summary" placeholder="변경 내용 요약" className="..." />

      {/* 업로드 진행률 */}
      {uploading && <ProgressBar value={progress} />}

      <button type="submit" disabled={!file || uploading}>업로드 및 인덱싱</button>
    </form>
  )
}
```

### 4-4. 라우트 보호 미들웨어

```typescript
// middleware.ts

import { NextRequest, NextResponse } from 'next/server'
import { jwtVerify } from 'jose'

const PUBLIC_ROUTES = ['/login']
const ADMIN_ROUTES = ['/admin']
const MANAGER_ROUTES = ['/documents/upload']

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  if (PUBLIC_ROUTES.includes(pathname)) return NextResponse.next()

  const token = request.cookies.get('access_token')?.value
  if (!token) {
    return NextResponse.redirect(new URL('/login', request.url))
  }

  try {
    const { payload } = await jwtVerify(
      token,
      new TextEncoder().encode(process.env.SECRET_KEY)
    )

    // Admin 전용 라우트 보호
    if (ADMIN_ROUTES.some(r => pathname.startsWith(r)) && payload.role !== 'admin') {
      return NextResponse.redirect(new URL('/chat', request.url))
    }

    // Manager 전용 라우트 보호
    if (MANAGER_ROUTES.some(r => pathname.startsWith(r)) && !['admin', 'manager'].includes(payload.role as string)) {
      return NextResponse.redirect(new URL('/chat', request.url))
    }

  } catch {
    return NextResponse.redirect(new URL('/login', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)']
}
```

---

## 5. API 클라이언트 설정

```typescript
// lib/api.ts

import axios from 'axios'

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1',
  withCredentials: true,  // 쿠키 전송
})

// 요청 인터셉터: 토큰 자동 부착
api.interceptors.request.use((config) => {
  const token = document.cookie.match(/access_token=([^;]+)/)?.[1]
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 응답 인터셉터: 401 시 로그인 리다이렉트
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
```

---

## 6. 추가 패키지 설치

```bash
# hotel-rag 프로젝트에 추가 설치
npm install \
  react-dropzone \           # 드래그앤드롭 업로드
  react-markdown \           # 마크다운 렌더링
  remark-gfm \              # GitHub Flavored Markdown
  jose \                    # JWT 검증 (Edge Runtime 호환)
  axios \                   # HTTP 클라이언트
  lucide-react \            # 아이콘
  @radix-ui/react-dialog \  # 모달
  @radix-ui/react-select \  # 셀렉트
  date-fns                  # 날짜 포맷
```

---

## 7. 환경 변수 (.env.local)

```bash
# hotel-rag/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
SECRET_KEY=your-256-bit-secret-key-here  # 백엔드와 동일 키
```

---

## 8. UI/UX 가이드라인

| 항목 | 결정 |
|------|------|
| 색상 테마 | 흰색 배경 + 파란색 액센트 (Tailwind `blue-600`) |
| 채팅 레이아웃 | 좌측 사이드바(세션 이력) + 우측 채팅창 |
| 응답 중 표시 | 3점 dot 애니메이션 |
| 소스 패널 | 기본 접힘, 클릭 시 펼침 |
| 모바일 | 사이드바 드로어 방식 (768px 이하) |
| 에러 표시 | toast 알림 (우측 상단) |
