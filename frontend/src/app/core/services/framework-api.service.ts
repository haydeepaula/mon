import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import {
  FrameworkVersao,
  Recuperacao,
  Requisito,
  RequisitoInput,
  StatusValidacaoRequisito,
  StatusVersao,
} from '../models/diagnostico.models';

export interface RequisitoFiltro {
  versao?: string | null;
  tipo?: string;
  grupo?: string;
  formato?: string;
  status_validacao?: string;
  q?: string;
}

/** Endpoints do framework de critérios (TCC, seção 3.5). */
@Injectable({ providedIn: 'root' })
export class FrameworkApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/framework';

  versions() {
    return firstValueFrom(this.http.get<FrameworkVersao[]>(`${this.base}/versoes`));
  }

  createVersion(versao: string, descricao = '', ativar = false) {
    return firstValueFrom(this.http.post<FrameworkVersao>(`${this.base}/versoes`, { versao, descricao, ativar }));
  }

  cloneVersion(id: string, versao: string) {
    return firstValueFrom(this.http.post<FrameworkVersao>(`${this.base}/versoes/${id}/clonar`, { versao }));
  }

  updateVersion(id: string, changes: { status?: StatusVersao; ativa?: boolean; descricao?: string; notas?: string }) {
    return firstValueFrom(this.http.patch<FrameworkVersao>(`${this.base}/versoes/${id}`, changes));
  }

  deleteVersion(id: string) {
    return firstValueFrom(this.http.delete<void>(`${this.base}/versoes/${id}`));
  }

  requirements(filtro: RequisitoFiltro = {}) {
    const entries = Object.entries(filtro).filter(([, value]) => value !== undefined && value !== null && value !== '');
    const params = new HttpParams({ fromObject: Object.fromEntries(entries) as Record<string, string> });
    return firstValueFrom(this.http.get<Requisito[]>(`${this.base}/requisitos`, { params }));
  }

  createRequirement(versao: string, data: RequisitoInput) {
    const params = new HttpParams({ fromObject: { versao } });
    return firstValueFrom(this.http.post<Requisito>(`${this.base}/requisitos`, data, { params }));
  }

  updateRequirement(versao: string, codigo: string, data: RequisitoInput) {
    const params = new HttpParams({ fromObject: { versao } });
    return firstValueFrom(this.http.put<Requisito>(`${this.base}/requisitos/${codigo}`, data, { params }));
  }

  deleteRequirement(versao: string, codigo: string) {
    const params = new HttpParams({ fromObject: { versao } });
    return firstValueFrom(this.http.delete<void>(`${this.base}/requisitos/${codigo}`, { params }));
  }

  reviewRequirement(versao: string, codigo: string, status: StatusValidacaoRequisito, comentario: string | null) {
    const params = new HttpParams({ fromObject: { versao } });
    return firstValueFrom(
      this.http.patch<Requisito>(`${this.base}/requisitos/${codigo}/validacao`, { status, comentario }, { params }),
    );
  }

  evidence(codigo: string, versao: string | null, curso: string | null, incluirNormativa = true) {
    const params = new HttpParams({
      fromObject: {
        ...(versao && { versao }),
        ...(curso && { curso }),
        incluir_normativa: String(incluirNormativa),
      },
    });
    return firstValueFrom(this.http.get<Recuperacao>(`${this.base}/requisitos/${codigo}/evidencias`, { params }));
  }

  importJson(versao: string, requisitos: unknown[], modo: 'mesclar' | 'substituir') {
    return firstValueFrom(
      this.http.post<{ versao: string; criados: number; atualizados: number; total: number }>(`${this.base}/importar`, {
        versao,
        modo,
        requisitos,
      }),
    );
  }

  importCsv(versao: string, file: File, modo: 'mesclar' | 'substituir') {
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('versao', versao);
    form.append('modo', modo);
    return firstValueFrom(
      this.http.post<{ versao: string; criados: number; atualizados: number; total: number }>(`${this.base}/importar/csv`, form),
    );
  }

  export(versao: string, formato: 'json' | 'csv') {
    const params = new HttpParams({ fromObject: { versao, formato } });
    return firstValueFrom(this.http.get(`${this.base}/exportar`, { params, responseType: 'blob' }));
  }
}
