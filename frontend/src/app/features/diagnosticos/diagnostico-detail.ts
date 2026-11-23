import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import {
  ALERTAS,
  CAUSAS,
  CausaDivergencia,
  CLASSIFICACAO_INFO,
  CLASSIFICACOES,
  Classificacao,
  Concordancia,
  Diagnostico,
  DiagnosticoItem,
  ETAPAS,
  Evidencia,
  STATUS_DIAGNOSTICO,
  TIPO_REQUISITO,
  ValidacaoInput,
} from '../../core/models/diagnostico.models';
import { apiErrorMessage } from '../../core/services/api-error';
import { DiagnosticoApi } from '../../core/services/diagnostico-api.service';
import { DownloadService } from '../../core/services/download.service';
import { ToastService } from '../../core/services/toast.service';
import { Icon } from '../../shared/components/icon';
import { DateTimePipe, Percent100Pipe } from '../../shared/pipes/format.pipes';

type Aba = 'revisao' | 'concordancia' | 'plano';
type Filtro = 'todos' | 'a_validar' | 'divergentes' | 'erros' | 'nc_pc';

interface FormValidacao extends ValidacaoInput {
  itemId: string;
}

@Component({
  selector: 'app-diagnostico-detail',
  imports: [FormsModule, Icon, DateTimePipe, Percent100Pipe],
  templateUrl: './diagnostico-detail.html',
  styleUrl: './diagnostico-detail.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DiagnosticoDetail implements OnInit {
  readonly id = input.required<string>();

  private readonly api = inject(DiagnosticoApi);
  private readonly toast = inject(ToastService);
  private readonly downloads = inject(DownloadService);
  private readonly router = inject(Router);

  protected readonly diagnostico = signal<Diagnostico | null>(null);
  protected readonly itens = signal<DiagnosticoItem[]>([]);
  protected readonly metricas = signal<Concordancia | null>(null);
  protected readonly aba = signal<Aba>('revisao');
  protected readonly filtro = signal<Filtro>('todos');
  protected readonly selecionadoId = signal<string | null>(null);
  protected readonly validacao = signal<FormValidacao | null>(null);
  protected readonly salvando = signal(false);
  protected readonly mostrarNormativos = signal(false);

  protected readonly classificacoes = CLASSIFICACOES;
  protected readonly classInfo = CLASSIFICACAO_INFO;
  protected readonly causas = CAUSAS;
  protected readonly tipoInfo = TIPO_REQUISITO;
  protected readonly statusInfo = STATUS_DIAGNOSTICO;
  protected readonly alertas = ALERTAS;
  protected readonly etapas = ETAPAS;
  protected readonly categorias: Classificacao[] = ['C', 'PC', 'NC', 'EI'];

  protected readonly selecionado = computed(() => this.itens().find((i) => i.id === this.selecionadoId()) ?? null);

  protected readonly itensFiltrados = computed(() => {
    const filtro = this.filtro();
    return this.itens().filter((item) => {
      switch (filtro) {
        case 'a_validar':
          return !item.classificacao_final;
        case 'divergentes':
          return !!item.classificacao_final && !!item.classificacao_proposta && item.classificacao_final !== item.classificacao_proposta;
        case 'erros':
          return item.proposta_status === 'erro';
        case 'nc_pc':
          return item.classificacao_final === 'NC' || item.classificacao_final === 'PC';
        default:
          return true;
      }
    });
  });

  protected readonly etapaAtual = computed(() => {
    const status = this.diagnostico()?.status;
    return this.etapas.findIndex((e) => status && e.status.includes(status));
  });

  protected readonly podeVerificar = computed(() => {
    const d = this.diagnostico();
    if (!d || d.status === 'verificando' || d.status === 'relatorio_emitido' || d.status === 'concluido') return false;
    return this.itens().some((i) => i.proposta_status !== 'gerada');
  });

  protected readonly podeValidar = computed(() => {
    const status = this.diagnostico()?.status;
    return status === 'em_validacao' || status === 'validado' || status === 'priorizado';
  });

  protected readonly execucao = computed(() => (this.diagnostico()?.config.ultima_execucao ?? null) as Record<string, string | number | null> | null);

  constructor() {
    const timer = setInterval(() => {
      if (this.diagnostico()?.status === 'verificando') this.carregar(false);
    }, 3000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  async ngOnInit(): Promise<void> {
    await this.carregar(true);
  }

  async carregar(selecionarPrimeiro = false): Promise<void> {
    try {
      const [diagnostico, itens] = await Promise.all([this.api.get(this.id()), this.api.items(this.id())]);
      this.diagnostico.set(diagnostico);
      this.itens.set(itens);
      if (selecionarPrimeiro && itens.length && !this.selecionadoId()) this.selecionar(itens[0]);
      else if (this.selecionado() && !this.validacao()) this.prepararForm(this.selecionado()!);
      if (this.aba() === 'concordancia') this.carregarMetricas();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected async carregarMetricas(): Promise<void> {
    try {
      this.metricas.set(await this.api.metrics(this.id()));
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected abrirAba(aba: Aba): void {
    this.aba.set(aba);
    if (aba === 'concordancia') this.carregarMetricas();
  }

  protected voltar(): void {
    this.router.navigate(['/admin/diagnosticos']);
  }

  protected async verificar(itemIds?: string[]): Promise<void> {
    try {
      await this.api.verify(this.id(), itemIds);
      this.toast.success('Verificação iniciada. As propostas aparecem aqui conforme forem geradas.');
      this.carregar();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  // Revisão e validação
  protected selecionar(item: DiagnosticoItem): void {
    this.selecionadoId.set(item.id);
    this.mostrarNormativos.set(false);
    this.prepararForm(item);
  }

  private prepararForm(item: DiagnosticoItem): void {
    this.validacao.set({
      itemId: item.id,
      classificacao_final: item.classificacao_final ?? item.classificacao_proposta ?? 'EI',
      conceito_final: item.conceito_final ?? item.conceito_proposto ?? null,
      divergencia_causa: item.divergencia_causa,
      comentario: item.comentario,
    });
    if (item.proposta_oculta) {
      this.validacao.update((v) => (v ? { ...v, classificacao_final: item.classificacao_final ?? 'EI', conceito_final: item.conceito_final } : v));
    }
  }

  protected escolher(form: FormValidacao, valor: Classificacao): void {
    this.validacao.set({ ...form, classificacao_final: valor });
  }

  protected escolherCausa(form: FormValidacao, causa: CausaDivergencia): void {
    this.validacao.set({ ...form, divergencia_causa: causa });
  }

  protected exigeCausa(item: DiagnosticoItem, form: FormValidacao): boolean {
    return item.proposta_status === 'gerada' && !item.proposta_oculta && !!item.classificacao_proposta && item.classificacao_proposta !== form.classificacao_final;
  }

  protected async salvar(item: DiagnosticoItem, form: FormValidacao, avancar: boolean): Promise<void> {
    if (this.exigeCausa(item, form) && !form.divergencia_causa) {
      this.toast.error('Informe a causa da divergência em relação à proposta.');
      return;
    }
    this.salvando.set(true);
    try {
      const atualizado = await this.api.validate(this.id(), item.id, {
        classificacao_final: form.classificacao_final,
        conceito_final: item.requisito.tipo === 'qualidade' ? form.conceito_final : null,
        divergencia_causa: form.divergencia_causa,
        comentario: form.comentario?.trim() || null,
      });
      this.itens.update((lista) => lista.map((i) => (i.id === atualizado.id ? atualizado : i)));
      this.diagnostico.set(await this.api.get(this.id()));
      if (atualizado.proposta_oculta === false && item.proposta_oculta) {
        this.toast.info(`Proposta do Mon revelada: ${atualizado.classificacao_proposta ?? '—'}.`);
      }
      const proximo = avancar ? this.proximoPendente(item) : null;
      if (proximo) this.selecionar(proximo);
      else this.prepararForm(atualizado);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    } finally {
      this.salvando.set(false);
    }
  }

  private proximoPendente(atual: DiagnosticoItem): DiagnosticoItem | null {
    const lista = this.itens();
    const inicio = lista.findIndex((i) => i.id === atual.id);
    return [...lista.slice(inicio + 1), ...lista.slice(0, inicio)].find((i) => !i.classificacao_final && i.proposta_status !== 'pendente') ?? null;
  }

  protected citada(item: DiagnosticoItem, evidencia: Evidencia): boolean {
    return !!evidencia.n && !!item.proposta?.citacoes.includes(evidencia.n);
  }

  protected async baixar(evidencia: Evidencia): Promise<void> {
    if (!evidencia.document_id) return;
    await this.downloads.document(evidencia.document_id, evidencia.documento);
  }

  protected contagem(classificacao: Classificacao): number {
    return this.diagnostico()?.resumo.classificacao_final[classificacao] ?? 0;
  }

  protected tomKappa(valor: number | null | undefined): string {
    if (valor == null) return '';
    return valor >= 0.6 ? 'good' : valor >= 0.4 ? 'mid' : 'bad';
  }

  protected tipoLabel(valor: string): string {
    return (this.tipoInfo as Record<string, string>)[valor] ?? valor;
  }

  protected causaLabel(valor: string): string {
    return this.causas.find((c) => c.value === valor)?.label ?? valor;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  protected entradas(obj: object | undefined | null): [string, any][] {
    return Object.entries(obj ?? {});
  }
}
