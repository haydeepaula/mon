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
import { ModelInfo, Provider } from '../../core/models/api.models';
import { apiErrorMessage } from '../../core/services/api-error';
import { ConfirmService } from '../../core/services/confirm.service';
import { AdminApi } from '../../core/services/admin-api.service';
import { DiagnosticoApi } from '../../core/services/diagnostico-api.service';
import { DownloadService } from '../../core/services/download.service';
import { ToastService } from '../../core/services/toast.service';
import { Icon } from '../../shared/components/icon';
import { DateTimePipe, Percent100Pipe } from '../../shared/pipes/format.pipes';
import { MarkdownPipe } from '../../shared/pipes/markdown.pipe';

type Aba = 'revisao' | 'priorizacao' | 'relatorio' | 'concordancia' | 'plano';

interface LinhaGut {
  item: DiagnosticoItem;
  g: number | null;
  u: number | null;
  t: number | null;
}
type Filtro = 'todos' | 'a_validar' | 'divergentes' | 'erros' | 'nc_pc';

interface FormValidacao extends ValidacaoInput {
  itemId: string;
}

@Component({
  selector: 'app-diagnostico-detail',
  imports: [FormsModule, Icon, DateTimePipe, Percent100Pipe, MarkdownPipe],
  templateUrl: './diagnostico-detail.html',
  styleUrl: './diagnostico-detail.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DiagnosticoDetail implements OnInit {
  readonly id = input.required<string>();

  private readonly api = inject(DiagnosticoApi);
  private readonly toast = inject(ToastService);
  private readonly downloads = inject(DownloadService);
  private readonly confirm = inject(ConfirmService);
  private readonly admin = inject(AdminApi);
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
  protected readonly gut = signal<LinhaGut[]>([]);
  protected readonly relatorio = signal<string | null>(null);
  protected readonly notas = [1, 2, 3, 4, 5];
  protected readonly devolutiva = signal<{ data: string; participantes: string; resultado: 'aceito' | 'revisado'; observacoes: string } | null>(null);
  protected readonly comparar = signal<{ provider: string; model: string; reasoning: string; nome: string } | null>(null);
  protected readonly provedores = signal<Provider[]>([]);
  protected readonly modelos = signal<ModelInfo[]>([]);

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

  protected readonly podePriorizar = computed(() => {
    const status = this.diagnostico()?.status;
    return status === 'validado' || status === 'priorizado';
  });

  protected readonly podeEmitir = computed(() => {
    const status = this.diagnostico()?.status;
    return status === 'priorizado' || (status === 'validado' && this.gut().length === 0);
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
      // Diagnóstico clonado: compara as propostas com as decisões do diagnóstico de referência.
      this.metricas.set(await this.api.metrics(this.id(), this.diagnostico()?.referencia_id));
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected abrirAba(aba: Aba): void {
    this.aba.set(aba);
    if (aba === 'concordancia') this.carregarMetricas();
    if (aba === 'priorizacao' || aba === 'relatorio') this.carregarGut();
    if (aba === 'relatorio') this.carregarRelatorio();
  }

  // Priorização GUT (etapa 6)
  protected async carregarGut(): Promise<void> {
    try {
      const itens = await this.api.prioritization(this.id());
      this.gut.set(itens.map((item) => ({ item, g: item.gut_g, u: item.gut_u, t: item.gut_t })));
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected aplicarSugestoes(): void {
    this.gut.update((linhas) =>
      linhas.map((l) => ({ ...l, g: l.g ?? l.item.gut_sugestao.g ?? null, u: l.u ?? l.item.gut_sugestao.u ?? null })),
    );
  }

  protected produto(linha: LinhaGut): number | null {
    return linha.g && linha.u && linha.t ? linha.g * linha.u * linha.t : null;
  }

  protected alterado(linha: LinhaGut): boolean {
    return linha.g !== linha.item.gut_g || linha.u !== linha.item.gut_u || linha.t !== linha.item.gut_t;
  }

  protected async salvarGut(): Promise<void> {
    const pendentes = this.gut().filter((l) => this.alterado(l));
    if (pendentes.some((l) => !l.g || !l.u || !l.t)) {
      this.toast.error('Preencha G, U e T de todos os itens alterados.');
      return;
    }
    this.salvando.set(true);
    try {
      for (const linha of pendentes) await this.api.setGut(this.id(), linha.item.id, linha.g!, linha.u!, linha.t!);
      this.toast.success('Priorização salva.');
      await Promise.all([this.carregarGut(), this.carregar()]);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    } finally {
      this.salvando.set(false);
    }
  }

  // Relatório (etapa 7)
  protected async carregarRelatorio(): Promise<void> {
    try {
      this.relatorio.set(await this.api.report(this.id()));
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected async emitirRelatorio(): Promise<void> {
    const ok = await this.confirm.ask({
      title: 'Emitir relatório',
      message: 'O relatório será congelado. Validações e priorização não poderão mais ser alteradas neste diagnóstico.',
      confirmText: 'Emitir',
    });
    if (!ok) return;
    try {
      this.diagnostico.set(await this.api.issueReport(this.id()));
      this.toast.success('Relatório emitido.');
      this.carregarRelatorio();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected baixarRelatorio(): void {
    const conteudo = this.relatorio();
    if (!conteudo) return;
    const url = URL.createObjectURL(new Blob([conteudo], { type: 'text/markdown;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `relatorio-${this.diagnostico()?.nome ?? this.id()}.md`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
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

  // Exportação DOCX e devolutiva (etapas 7 e 8)
  protected async baixarDocx(): Promise<void> {
    try {
      const blob = await this.api.reportDocx(this.id());
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `relatorio-${this.diagnostico()?.nome ?? this.id()}.docx`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected abrirDevolutiva(): void {
    this.devolutiva.set({ data: new Date().toISOString().slice(0, 10), participantes: 'Coordenação do curso, NDE', resultado: 'aceito', observacoes: '' });
  }

  protected async registrarDevolutiva(): Promise<void> {
    const form = this.devolutiva();
    if (!form) return;
    try {
      this.diagnostico.set(
        await this.api.feedback(this.id(), {
          data: form.data || null,
          participantes: form.participantes.split(',').map((p) => p.trim()).filter(Boolean),
          resultado: form.resultado,
          observacoes: form.observacoes.trim() || null,
        }),
      );
      this.devolutiva.set(null);
      this.toast.success(form.resultado === 'aceito' ? 'Diagnóstico concluído.' : 'Diagnóstico reaberto para revisão.');
      await this.carregar();
      this.carregarRelatorio();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  // Comparação entre modelos (seção 3.8)
  protected async abrirComparacao(): Promise<void> {
    try {
      const provedores = (await this.admin.providers()).filter((p) => p.configured);
      this.provedores.set(provedores);
      const provider = provedores[0]?.id ?? 'google';
      this.comparar.set({ provider, model: '', reasoning: 'low', nome: '' });
      this.carregarModelos(provider);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected async carregarModelos(provider: string): Promise<void> {
    this.modelos.set([]);
    try {
      this.modelos.set(await this.admin.models(provider));
    } catch {
      this.modelos.set([]);
    }
  }

  protected async criarComparacao(): Promise<void> {
    const form = this.comparar();
    if (!form?.model.trim()) {
      this.toast.error('Escolha o modelo.');
      return;
    }
    try {
      const clone = await this.api.clone(this.id(), {
        nome: form.nome.trim() || null,
        llm_provider: form.provider,
        llm_model: form.model.trim(),
        reasoning_level: form.reasoning,
      });
      this.comparar.set(null);
      this.toast.success('Diagnóstico de comparação criado. Execute a verificação nele e veja a concordância.');
      await this.router.navigate(['/admin/diagnosticos', clone.id]);
      this.selecionadoId.set(null);
      this.validacao.set(null);
      this.metricas.set(null);
      this.aba.set('revisao');
      await this.carregar(true);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }
}
