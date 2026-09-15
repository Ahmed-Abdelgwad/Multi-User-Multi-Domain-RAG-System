import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { LoginPage } from './auth/LoginPage'
import { RegisterPage } from './auth/RegisterPage'
import { AppShell } from './layout/AppShell'
import { DomainListPage } from './domains/DomainListPage'
import { DomainDetailPage } from './domains/DomainDetailPage'
import { DocumentsPage } from './ingestion/DocumentsPage'
import { DocumentChunksPage } from './ingestion/DocumentChunksPage'
import { QueryPage } from './query/QueryPage'
import { EvaluationLayout } from './evaluation/EvaluationLayout'
import { QualityDashboardPage } from './evaluation/QualityDashboardPage'
import { ModerationQueuePage } from './evaluation/ModerationQueuePage'
import { GoldenQAPage } from './evaluation/GoldenQAPage'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route element={<RequireAuth />}>
              <Route element={<AppShell />}>
                <Route index element={<Navigate to="/domains" replace />} />
                <Route path="/domains" element={<DomainListPage />} />
                <Route path="/domains/:domainId" element={<DomainDetailPage />} />
                <Route path="/domains/:domainId/documents" element={<DocumentsPage />} />
                <Route path="/domains/:domainId/documents/:documentId/chunks" element={<DocumentChunksPage />} />
                <Route path="/domains/:domainId/evaluation" element={<EvaluationLayout />}>
                  <Route index element={<Navigate to="dashboard" replace />} />
                  <Route path="dashboard" element={<QualityDashboardPage />} />
                  <Route path="moderation" element={<ModerationQueuePage />} />
                  <Route path="golden-qa" element={<GoldenQAPage />} />
                </Route>
                <Route path="/query" element={<QueryPage />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/domains" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
