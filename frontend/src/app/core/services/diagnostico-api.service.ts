import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Job } from '../models/api.models';
import {
  Concordancia,
  Diagnostico,
  DiagnosticoInput,
  DiagnosticoItem,
  Escopo,
  Requisito,
  ValidacaoInput,
} from '../models/diagnostico.models';

/** Endpoints do processo de diagnóstico (Quadro 9). */
@Injectable({ providedIn: 'root' })
export class DiagnosticoApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/diagnosticos';

  list() {
    return firstValueFrom(this.http.get<Diagnostico[]>(this.base));
  }

  get(id: string) {
    return firstValueFrom(this.http.get<Diagnostico>(`${this.base}/${id}`));
  }

  create(data: DiagnosticoInput) {
    return firstValueFrom(this.http.post<Diagnostico>(this.base, data));
  }

  update(id: string, data: DiagnosticoInput) {
    return firstValueFrom(this.http.patch<Diagnostico>(`${this.base}/${id}`, data));
  }

  remove(id: string) {
    return firstValueFrom(this.http.delete<void>(`${this.base}/${id}`));
  }

  applicable(escopo: Partial<Escopo>, versao?: string | null) {
    const params = new HttpParams({ fromObject: versao ? { versao } : {} });
    return firstValueFrom(this.http.post<Requisito[]>(`${this.base}/requisitos-aplicaveis`, escopo, { params }));
  }

  verify(id: string, itemIds?: string[]) {
    return firstValueFrom(this.http.post<Job>(`${this.base}/${id}/verificar`, { item_ids: itemIds ?? null }));
  }

  items(id: string) {
    return firstValueFrom(this.http.get<DiagnosticoItem[]>(`${this.base}/${id}/itens`));
  }

  validate(id: string, itemId: string, data: ValidacaoInput) {
    return firstValueFrom(this.http.put<DiagnosticoItem>(`${this.base}/${id}/itens/${itemId}/validacao`, data));
  }

  metrics(id: string, referencia?: string | null) {
    const params = new HttpParams({ fromObject: referencia ? { referencia } : {} });
    return firstValueFrom(this.http.get<Concordancia>(`${this.base}/${id}/metricas`, { params }));
  }
}
