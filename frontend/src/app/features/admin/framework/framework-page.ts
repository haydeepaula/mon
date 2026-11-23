import { ChangeDetectionStrategy, Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  FormatoOferta,
  FrameworkVersao,
  Recuperacao,
  Requisito,
  RequisitoInput,
  StatusValidacaoRequisito,
  StatusVersao,
  TIPO_REQUISITO,
  TipoRequisito,
} from '../../../core/models/diagnostico.models';
import { AdminApi } from '../../../core/services/admin-api.service';
import { apiErrorMessage } from '../../../core/services/api-error';
import { ConfirmService } from '../../../core/services/confirm.service';
import { FrameworkApi } from '../../../core/services/framework-api.service';
import { ToastService } from '../../../core/services/toast.service';
import { Icon } from '../../../shared/components/icon';
import { DateTimePipe, Percent100Pipe } from '../../../shared/pipes/format.pipes';

interface Editor {
  novo: boolean;
  codigo: string;
  grupo: string;
  fonte_documento: string;
  fonte_dispositivo: string;
  texto: string;
  tipo: TipoRequisito;
  dimensao_inep: number | null;
  indicador_inep: string;
  evidencia_esperada: string;
  documentos_provaveis: string[];
  consulta_padrao: string;
  termos_chave: string;
  gravidade_base: number | null;
  formatos: FormatoOferta[];
  situacao_normativa: 'vigente' | 'tendencia';
  prazo_referencia: string;
}

export const STATUS_VERSAO: Record<StatusVersao, { label: string; tone: string }> = {
  rascunho: { label: 'Rascunho', tone: '' },
  em_validacao: { label: 'Em validação', tone: 'info' },
  validado: { label: 'Validado', tone: 'success' },
  arquivado: { label: 'Arquivado', tone: 'warning' },
};

export const STATUS_REQUISITO: Record<StatusValidacaoRequisito, { label: string; tone: string }> = {
  pendente: { label: 'Pendente', tone: '' },
  aprovado: { label: 'Aprovado', tone: 'success' },
  ajustar: { label: 'Ajustar', tone: 'warning' },
};

@Component({
  selector: 'app-framework-page',
  imports: [FormsModule, Icon, DateTimePipe, Percent100Pipe],
  templateUrl: './framework-page.html',
  styleUrl: './framework-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FrameworkPage implements OnInit {
  private readonly api = inject(FrameworkApi);
  private readonly admin = inject(AdminApi);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmService);

  protected readonly versoes = signal<FrameworkVersao[]>([]);
  protected readonly versaoSel = signal<string | null>(null);
  protected readonly requisitos = signal<Requisito[]>([]);
  protected readonly loading = signal(true);
  protected readonly selecionado = signal<Requisito | null>(null);
  protected readonly editor = signal<Editor | null>(null);
  protected readonly recuperacao = signal<Recuperacao | null>(null);
  protected readonly testando = signal(false);
  protected readonly importDialog = signal(false);
  protected readonly cloneDialog = signal<string | null>(null);
  protected readonly tiposDocumento = signal<string[]>([]);

  protected filtroTipo = '';
  protected filtroStatus = '';
  protected busca = '';
  protected comentario = '';
  protected cursoTeste = 'eng-producao-ead';
  protected importModo: 'mesclar' | 'substituir' = 'mesclar';

  protected readonly statusVersao = STATUS_VERSAO;
  protected readonly statusReq = STATUS_REQUISITO;
  protected readonly tipoInfo = TIPO_REQUISITO;
  protected readonly tipos = Object.entries(TIPO_REQUISITO) as [TipoRequisito, string][];
  protected readonly formatos: FormatoOferta[] = ['presencial', 'semipresencial', 'distancia'];

  protected readonly versao = computed(() => this.versoes().find((v) => v.versao === this.versaoSel()) ?? null);
  protected readonly editavel = computed(() => {
    const status = this.versao()?.status;
    return status === 'rascunho' || status === 'em_validacao';
  });
  protected readonly contagem = computed(() => {
    const lista = this.requisitos();
    return {
      total: lista.length,
      aprovados: lista.filter((r) => r.status_validacao === 'aprovado').length,
      ajustar: lista.filter((r) => r.status_validacao === 'ajustar').length,
      pendentes: lista.filter((r) => r.status_validacao === 'pendente').length,
    };
  });

  async ngOnInit(): Promise<void> {
    await this.carregarVersoes();
    this.admin
      .documentVocabulary()
      .then((v) => this.tiposDocumento.set(v.tipos_documento.institucional))
      .catch(() => undefined);
  }

  protected async carregarVersoes(manterSelecao = true): Promise<void> {
    try {
      const versoes = await this.api.versions();
      this.versoes.set(versoes);
      const atual = manterSelecao && versoes.some((v) => v.versao === this.versaoSel()) ? this.versaoSel() : null;
      this.versaoSel.set(atual ?? versoes.find((v) => v.ativa)?.versao ?? versoes[0]?.versao ?? null);
      await this.carregarRequisitos();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected async carregarRequisitos(): Promise<void> {
    const versao = this.versaoSel();
    if (!versao) return;
    try {
      this.requisitos.set(
        await this.api.requirements({ versao, tipo: this.filtroTipo, status_validacao: this.filtroStatus, q: this.busca.trim() }),
      );
      const sel = this.selecionado();
      if (sel) this.selecionado.set(this.requisitos().find((r) => r.codigo === sel.codigo) ?? null);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected trocarVersao(versao: string): void {
    this.versaoSel.set(versao);
    this.selecionado.set(null);
    this.editor.set(null);
    this.carregarRequisitos();
  }

  // Versões
  protected async mudarStatus(status: StatusVersao): Promise<void> {
    const versao = this.versao();
    if (!versao) return;
    const mensagens: Record<StatusVersao, string> = {
      rascunho: 'A versão volta a rascunho.',
      em_validacao: 'A versão será enviada para a revisão do orientador.',
      validado: 'A versão ficará imutável. Para alterá-la depois, será preciso clonar.',
      arquivado: 'A versão ficará imutável e não poderá ser ativada.',
    };
    const ok = await this.confirm.ask({ title: `Marcar como ${STATUS_VERSAO[status].label.toLowerCase()}`, message: mensagens[status], confirmText: 'Confirmar' });
    if (!ok) return;
    try {
      await this.api.updateVersion(versao.id, { status });
      await this.carregarVersoes();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected async ativar(): Promise<void> {
    const versao = this.versao();
    if (!versao) return;
    try {
      await this.api.updateVersion(versao.id, { ativa: true });
      this.toast.success(`Versão ${versao.versao} ativa: novos diagnósticos passam a usá-la.`);
      await this.carregarVersoes();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected clonar(): void {
    const versao = this.versao();
    if (versao) this.cloneDialog.set(this.proximaVersao(versao.versao));
  }

  protected async confirmarClone(nome: string): Promise<void> {
    const versao = this.versao();
    if (!versao || !nome.trim()) return;
    try {
      await this.api.cloneVersion(versao.id, nome.trim());
      this.cloneDialog.set(null);
      this.versaoSel.set(nome.trim());
      this.toast.success(`Versão ${nome.trim()} criada como rascunho.`);
      await this.carregarVersoes();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  private proximaVersao(versao: string): string {
    const partes = versao.split('.');
    const ultimo = Number(partes.at(-1));
    if (Number.isNaN(ultimo)) return `${versao}-1`;
    partes[partes.length - 1] = String(ultimo + 1);
    return partes.join('.');
  }

  protected async exportar(formato: 'json' | 'csv'): Promise<void> {
    const versao = this.versaoSel();
    if (!versao) return;
    try {
      const blob = await this.api.export(versao, formato);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `framework-${versao}.${formato}`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected async importar(input: HTMLInputElement): Promise<void> {
    const file = input.files?.[0];
    input.value = '';
    const versao = this.versaoSel();
    if (!file || !versao) return;
    try {
      let resultado;
      if (file.name.toLowerCase().endsWith('.csv')) {
        resultado = await this.api.importCsv(versao, file, this.importModo);
      } else {
        const dados = JSON.parse(await file.text());
        const itens = Array.isArray(dados) ? dados : (dados.requisitos ?? []);
        resultado = await this.api.importJson(versao, itens, this.importModo);
      }
      this.importDialog.set(false);
      this.toast.success(`${resultado.criados} criado(s), ${resultado.atualizados} atualizado(s); ${resultado.total} no total.`);
      await this.carregarVersoes();
    } catch (error) {
      this.toast.error(apiErrorMessage(error, 'Arquivo inválido.'));
    }
  }

  // Requisitos
  protected selecionar(requisito: Requisito): void {
    this.selecionado.set(requisito);
    this.editor.set(null);
    this.recuperacao.set(null);
    this.comentario = requisito.comentario_validacao ?? '';
  }

  protected novo(): void {
    this.selecionado.set(null);
    this.recuperacao.set(null);
    this.editor.set({
      novo: true, codigo: '', grupo: '', fonte_documento: '', fonte_dispositivo: '', texto: '', tipo: 'legal',
      dimensao_inep: null, indicador_inep: '', evidencia_esperada: '', documentos_provaveis: [], consulta_padrao: '',
      termos_chave: '', gravidade_base: null, formatos: [], situacao_normativa: 'vigente', prazo_referencia: '',
    });
  }

  protected editar(r: Requisito): void {
    this.editor.set({
      novo: false,
      codigo: r.codigo,
      grupo: r.grupo,
      fonte_documento: r.fonte_documento,
      fonte_dispositivo: r.fonte_dispositivo ?? '',
      texto: r.texto,
      tipo: r.tipo,
      dimensao_inep: r.dimensao_inep,
      indicador_inep: r.indicador_inep ?? '',
      evidencia_esperada: r.evidencia_esperada,
      documentos_provaveis: [...r.documentos_provaveis],
      consulta_padrao: r.consulta_padrao ?? '',
      termos_chave: r.termos_chave.join(', '),
      gravidade_base: r.gravidade_base,
      formatos: [...r.formatos],
      situacao_normativa: r.situacao_normativa,
      prazo_referencia: r.prazo_referencia ?? '',
    });
  }

  protected alternar<T>(lista: T[], valor: T): T[] {
    return lista.includes(valor) ? lista.filter((v) => v !== valor) : [...lista, valor];
  }

  protected async salvar(e: Editor): Promise<void> {
    const versao = this.versaoSel();
    if (!versao) return;
    const dados: RequisitoInput = {
      grupo: e.grupo.trim() || undefined,
      fonte_documento: e.fonte_documento.trim(),
      fonte_dispositivo: e.fonte_dispositivo.trim() || null,
      texto: e.texto.trim(),
      tipo: e.tipo,
      dimensao_inep: e.tipo === 'qualidade' ? e.dimensao_inep : null,
      indicador_inep: e.tipo === 'qualidade' ? e.indicador_inep.trim() || null : null,
      evidencia_esperada: e.evidencia_esperada.trim(),
      documentos_provaveis: e.documentos_provaveis,
      consulta_padrao: e.consulta_padrao.trim() || null,
      termos_chave: e.termos_chave.split(',').map((t) => t.trim()).filter(Boolean),
      gravidade_base: e.gravidade_base,
      formatos: e.formatos,
      situacao_normativa: e.situacao_normativa,
      prazo_referencia: e.prazo_referencia || null,
    };
    try {
      const salvo = e.novo
        ? await this.api.createRequirement(versao, { ...dados, codigo: e.codigo.trim().toUpperCase() })
        : await this.api.updateRequirement(versao, e.codigo, dados);
      this.editor.set(null);
      await this.carregarVersoes();
      this.selecionar(this.requisitos().find((r) => r.codigo === salvo.codigo) ?? salvo);
      this.toast.success(`Requisito ${salvo.codigo} salvo.`);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected async excluir(r: Requisito): Promise<void> {
    const versao = this.versaoSel();
    if (!versao) return;
    const ok = await this.confirm.ask({ title: `Excluir ${r.codigo}`, message: r.texto, confirmText: 'Excluir', danger: true });
    if (!ok) return;
    try {
      await this.api.deleteRequirement(versao, r.codigo);
      this.selecionado.set(null);
      await this.carregarVersoes();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected async revisar(r: Requisito, status: StatusValidacaoRequisito): Promise<void> {
    const versao = this.versaoSel();
    if (!versao) return;
    if (status === 'ajustar' && !this.comentario.trim()) {
      this.toast.error('Descreva o ajuste necessário no comentário.');
      return;
    }
    try {
      const atualizado = await this.api.reviewRequirement(versao, r.codigo, status, this.comentario.trim() || null);
      await this.carregarVersoes();
      const lista = this.requisitos();
      const proximo = lista.slice(lista.findIndex((x) => x.codigo === r.codigo) + 1).find((x) => x.status_validacao === 'pendente');
      this.selecionar(status === 'aprovado' && proximo ? proximo : atualizado);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected async testarRecuperacao(r: Requisito): Promise<void> {
    this.testando.set(true);
    try {
      this.recuperacao.set(await this.api.evidence(r.codigo, this.versaoSel(), this.cursoTeste.trim() || null, true));
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    } finally {
      this.testando.set(false);
    }
  }
}
