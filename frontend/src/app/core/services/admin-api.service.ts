import { HttpClient, HttpEvent, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom, Observable } from 'rxjs';

import {
  Colecao,
  DocumentItem,
  DocumentStats,
  DocumentVocabulary,
  EvalCase,
  EvalCaseInput,
  EvalRun,
  EvalRunDetail,
  Job,
  JobDetail,
  ModelInfo,
  ModelTestResult,
  Provider,
  RagSettings,
  UploadItem,
} from '../models/api.models';

export interface DocumentClassification {
  colecao: Colecao;
  tipo_documento: string | null;
  curso: string | null;
}

/** Endpoints da área administrativa: documentos, jobs, modelos e avaliação. */
@Injectable({ providedIn: 'root' })
export class AdminApi {
  private readonly http = inject(HttpClient);

  // Documentos
  documents(q = '', status = '', colecao = '') {
    const params = new HttpParams({
      fromObject: { ...(q && { q }), ...(status && { status_filter: status }), ...(colecao && { colecao }) },
    });
    return firstValueFrom(this.http.get<DocumentItem[]>('/api/documents', { params }));
  }

  documentStats() {
    return firstValueFrom(this.http.get<DocumentStats>('/api/documents/stats'));
  }

  documentNames() {
    return firstValueFrom(this.http.get<string[]>('/api/documents/names'));
  }

  documentVocabulary() {
    return firstValueFrom(this.http.get<DocumentVocabulary>('/api/documents/vocabulary'));
  }

  classifyDocument(id: string, data: DocumentClassification) {
    return firstValueFrom(this.http.patch<DocumentItem>(`/api/documents/${id}`, data));
  }

  upload(file: File, classificacao?: DocumentClassification): Observable<HttpEvent<UploadItem[]>> {
    const form = new FormData();
    form.append('files', file, file.name);
    if (classificacao) {
      form.append('colecao', classificacao.colecao);
      if (classificacao.tipo_documento) form.append('tipo_documento', classificacao.tipo_documento);
      if (classificacao.curso) form.append('curso', classificacao.curso);
    }
    return this.http.post<UploadItem[]>('/api/documents/upload', form, {
      reportProgress: true,
      observe: 'events',
    });
  }

  reindexDocument(id: string) {
    return firstValueFrom(this.http.post<Job>(`/api/documents/${id}/reindex`, {}));
  }

  deleteDocument(id: string) {
    return firstValueFrom(this.http.delete<void>(`/api/documents/${id}`));
  }

  downloadDocument(id: string) {
    return firstValueFrom(this.http.get(`/api/documents/${id}/download`, { responseType: 'blob' }));
  }

  // Jobs
  jobs(status = '', type = '') {
    const params = new HttpParams({ fromObject: { ...(status && { status }), ...(type && { type }) } });
    return firstValueFrom(this.http.get<Job[]>('/api/jobs', { params }));
  }

  job(id: string) {
    return firstValueFrom(this.http.get<JobDetail>(`/api/jobs/${id}`));
  }

  jobStats() {
    return firstValueFrom(this.http.get<Record<string, number>>('/api/jobs/stats'));
  }

  syncFolder() {
    return firstValueFrom(this.http.post<Job>('/api/jobs/sync-folder', {}));
  }

  reindexAll() {
    return firstValueFrom(this.http.post<Job>('/api/jobs/reindex-all', {}));
  }

  cancelJob(id: string) {
    return firstValueFrom(this.http.post<Job>(`/api/jobs/${id}/cancel`, {}));
  }

  retryJob(id: string) {
    return firstValueFrom(this.http.post<Job>(`/api/jobs/${id}/retry`, {}));
  }

  // Modelos e configurações do RAG
  settings() {
    return firstValueFrom(this.http.get<RagSettings>('/api/admin/settings'));
  }

  updateSettings(changes: Partial<RagSettings>) {
    return firstValueFrom(this.http.put<RagSettings>('/api/admin/settings', changes));
  }

  providers() {
    return firstValueFrom(this.http.get<Provider[]>('/api/admin/providers'));
  }

  models(provider: string) {
    return firstValueFrom(this.http.get<ModelInfo[]>(`/api/admin/models/${provider}`));
  }

  testModel(provider: string, model: string) {
    return firstValueFrom(this.http.post<ModelTestResult>('/api/admin/models/test', { provider, model }));
  }

  // Avaliação
  evalCases() {
    return firstValueFrom(this.http.get<EvalCase[]>('/api/evals/cases'));
  }

  createEvalCase(data: EvalCaseInput) {
    return firstValueFrom(this.http.post<EvalCase>('/api/evals/cases', data));
  }

  updateEvalCase(id: string, data: EvalCaseInput) {
    return firstValueFrom(this.http.put<EvalCase>(`/api/evals/cases/${id}`, data));
  }

  deleteEvalCase(id: string) {
    return firstValueFrom(this.http.delete<void>(`/api/evals/cases/${id}`));
  }

  importEvalCases(cases: EvalCaseInput[]) {
    return firstValueFrom(this.http.post<{ imported: number }>('/api/evals/cases/import', { cases }));
  }

  generateEvalCases(count: number) {
    return firstValueFrom(this.http.post<Job>('/api/evals/cases/generate', { count }));
  }

  evalRuns() {
    return firstValueFrom(this.http.get<EvalRun[]>('/api/evals/runs'));
  }

  evalRun(id: string) {
    return firstValueFrom(this.http.get<EvalRunDetail>(`/api/evals/runs/${id}`));
  }

  startEvalRun(name?: string, case_ids?: string[]) {
    return firstValueFrom(this.http.post<EvalRun>('/api/evals/runs', { name, case_ids }));
  }

  deleteEvalRun(id: string) {
    return firstValueFrom(this.http.delete<void>(`/api/evals/runs/${id}`));
  }
}
