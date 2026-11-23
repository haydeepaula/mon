import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import {
  Diagnostico,
  Escopo,
  FormatoOferta,
  FrameworkVersao,
  STATUS_DIAGNOSTICO,
  TIPO_REQUISITO,
  TipoRequisito,
} from '../../core/models/diagnostico.models';
import { apiErrorMessage } from '../../core/services/api-error';
import { ConfirmService } from '../../core/services/confirm.service';
import { DiagnosticoApi } from '../../core/services/diagnostico-api.service';
import { FrameworkApi } from '../../core/services/framework-api.service';
import { ToastService } from '../../core/services/toast.service';
import { Icon } from '../../shared/components/icon';
import { DateTimePipe } from '../../shared/pipes/format.pipes';

interface NovoDiagnostico {
  nome: string;
  curso: string;
  curso_nome: string;
  framework_versao: string;
  escopo: Escopo;
}

const ESCOPO_PADRAO: Escopo = {
  formato_oferta: 'semipresencial',
  proximo_ato: null,
  data_ato: null,
  incluir_tendencia: false,
  tipos: [],
  grupos: [],
  codigos: [],
  validacao_cega: false,
  incluir_normativa: true,
  observacoes: null,
};

@Component({
  selector: 'app-diagnosticos-page',
  imports: [FormsModule, Icon, DateTimePipe],
  templateUrl: './diagnosticos-page.html',
  styleUrl: './diagnosticos-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DiagnosticosPage implements OnInit {
  private readonly api = inject(DiagnosticoApi);
  private readonly frameworkApi = inject(FrameworkApi);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmService);
  private readonly router = inject(Router);

  protected readonly diagnosticos = signal<Diagnostico[]>([]);
  protected readonly versoes = signal<FrameworkVersao[]>([]);
  protected readonly loading = signal(true);
  protected readonly form = signal<NovoDiagnostico | null>(null);
  protected readonly aplicaveis = signal<number | null>(null);
  protected readonly saving = signal(false);

  protected readonly statusInfo = STATUS_DIAGNOSTICO;
  protected readonly tipos = Object.entries(TIPO_REQUISITO) as [TipoRequisito, string][];
  protected readonly formatos: { value: FormatoOferta; label: string }[] = [
    { value: 'presencial', label: 'Presencial' },
    { value: 'semipresencial', label: 'Semipresencial' },
    { value: 'distancia', label: 'A distância' },
  ];

  async ngOnInit(): Promise<void> {
    await this.refresh();
    this.loading.set(false);
  }

  async refresh(): Promise<void> {
    try {
      this.diagnosticos.set(await this.api.list());
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected async novo(): Promise<void> {
    try {
      const versoes = await this.frameworkApi.versions();
      this.versoes.set(versoes);
      const ativa = versoes.find((v) => v.ativa);
      this.form.set({
        nome: '',
        curso: 'eng-producao-ead',
        curso_nome: 'Engenharia de Produção EAD — CEFET/RJ',
        framework_versao: ativa?.versao ?? '',
        escopo: { ...ESCOPO_PADRAO, tipos: [], grupos: [], codigos: [] },
      });
      this.previa();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected toggleTipo(form: NovoDiagnostico, tipo: TipoRequisito): void {
    const atual = form.escopo.tipos;
    form.escopo.tipos = atual.includes(tipo) ? atual.filter((t) => t !== tipo) : [...atual, tipo];
    this.previa();
  }

  protected async previa(): Promise<void> {
    const form = this.form();
    if (!form) return;
    try {
      const requisitos = await this.api.applicable(this.escopoPayload(form.escopo), form.framework_versao || null);
      this.aplicaveis.set(requisitos.length);
    } catch {
      this.aplicaveis.set(null);
    }
  }

  protected async criar(form: NovoDiagnostico): Promise<void> {
    this.saving.set(true);
    try {
      const diagnostico = await this.api.create({
        nome: form.nome.trim() || null,
        curso: form.curso.trim() || null,
        curso_nome: form.curso_nome.trim() || null,
        framework_versao: form.framework_versao || null,
        escopo: this.escopoPayload(form.escopo),
      });
      this.form.set(null);
      this.router.navigate(['/admin/diagnosticos', diagnostico.id]);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    } finally {
      this.saving.set(false);
    }
  }

  protected abrir(diagnostico: Diagnostico): void {
    this.router.navigate(['/admin/diagnosticos', diagnostico.id]);
  }

  protected async excluir(diagnostico: Diagnostico, event: Event): Promise<void> {
    event.stopPropagation();
    const ok = await this.confirm.ask({
      title: 'Excluir diagnóstico',
      message: `"${diagnostico.nome}" e todas as propostas e validações serão excluídos.`,
      confirmText: 'Excluir',
      danger: true,
    });
    if (!ok) return;
    try {
      await this.api.remove(diagnostico.id);
      this.refresh();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected progresso(diagnostico: Diagnostico): number {
    return diagnostico.resumo.total ? diagnostico.resumo.validados / diagnostico.resumo.total : 0;
  }

  private escopoPayload(escopo: Escopo): Partial<Escopo> {
    return { ...escopo, data_ato: escopo.data_ato || null, observacoes: escopo.observacoes?.trim() || null };
  }
}
