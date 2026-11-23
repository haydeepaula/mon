import { ChangeDetectionStrategy, Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiKeyStatus, ApiKeyTest, ModelInfo, ModelTestResult, Provider, RagSettings } from '../../../core/models/api.models';
import { AdminApi } from '../../../core/services/admin-api.service';
import { apiErrorMessage } from '../../../core/services/api-error';
import { ConfirmService } from '../../../core/services/confirm.service';
import { ToastService } from '../../../core/services/toast.service';
import { Icon } from '../../../shared/components/icon';
import { DateTimePipe } from '../../../shared/pipes/format.pipes';

const RERANK_MODELS = [
  { id: 'rerank-v4.0-pro', label: 'rerank-v4.0-pro · maior qualidade' },
  { id: 'rerank-v4.0-fast', label: 'rerank-v4.0-fast · menor latência' },
  { id: 'rerank-v3.5', label: 'rerank-v3.5 · geração anterior' },
  { id: 'rerank-multilingual-v3.0', label: 'rerank-multilingual-v3.0' },
];

@Component({
  selector: 'app-models-page',
  imports: [FormsModule, Icon, DateTimePipe],
  templateUrl: './models-page.html',
  styleUrl: './models-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModelsPage implements OnInit {
  private readonly api = inject(AdminApi);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmService);

  // Chaves de API
  protected readonly keys = signal<ApiKeyStatus[]>([]);
  protected readonly editingKey = signal<string | null>(null);
  protected readonly keyBusy = signal<string | null>(null);
  protected readonly keyTests = signal<Record<string, ApiKeyTest>>({});
  protected newKey = '';
  protected skipTest = false;

  protected readonly providers = signal<Provider[]>([]);
  protected readonly provider = signal<'google' | 'openai'>('google');
  protected readonly models = signal<ModelInfo[]>([]);
  protected readonly modelsError = signal<string | null>(null);
  protected readonly loadingModels = signal(false);
  protected readonly settings = signal<RagSettings | null>(null);
  protected readonly saving = signal(false);
  protected readonly tests = signal<Record<string, ModelTestResult | 'loading'>>({});
  protected readonly search = signal('');
  protected form: RagSettings | null = null;
  protected readonly rerankModels = RERANK_MODELS;

  protected readonly filtered = computed(() => {
    const term = this.search().trim().toLowerCase();
    return this.models().filter(
      (m) => !term || m.id.toLowerCase().includes(term) || m.display_name.toLowerCase().includes(term),
    );
  });

  protected readonly providerConfigured = computed(
    () => this.providers().find((p) => p.id === this.provider())?.configured ?? false,
  );

  async ngOnInit(): Promise<void> {
    try {
      const [providers, settings, keys] = await Promise.all([this.api.providers(), this.api.settings(), this.api.apiKeys()]);
      this.providers.set(providers);
      this.keys.set(keys);
      this.applySettings(settings);
      this.provider.set(settings.llm_provider === 'openai' ? 'openai' : 'google');
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
    this.loadModels();
  }

  protected editKey(id: string): void {
    this.editingKey.set(id);
    this.newKey = '';
    this.skipTest = false;
  }

  protected async saveKey(key: ApiKeyStatus): Promise<void> {
    const value = this.newKey.trim();
    if (value.length < 8) {
      this.toast.error('Cole a chave de API completa.');
      return;
    }
    this.keyBusy.set(key.id);
    try {
      this.keys.set(await this.api.saveApiKey(key.id, value, !this.skipTest));
      this.newKey = '';
      this.editingKey.set(null);
      this.keyTests.update((t) => ({ ...t, [key.id]: undefined as unknown as ApiKeyTest }));
      this.toast.success(`Chave ${key.nome} salva${this.skipTest ? ' (sem teste)' : ' e testada'}. Vale em até 10 s, sem reiniciar.`);
      await this.refreshProviders();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    } finally {
      this.keyBusy.set(null);
    }
  }

  protected async testKey(key: ApiKeyStatus): Promise<void> {
    this.keyBusy.set(key.id);
    try {
      const result = await this.api.testApiKey(key.id);
      this.keyTests.update((t) => ({ ...t, [key.id]: result }));
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    } finally {
      this.keyBusy.set(null);
    }
  }

  protected async removeKey(key: ApiKeyStatus): Promise<void> {
    const ok = await this.confirm.ask({
      title: `Remover chave ${key.nome}`,
      message: `A chave cadastrada pela interface será apagada. Se houver ${key.variavel} no .env, ela volta a valer.`,
      confirmText: 'Remover',
      danger: true,
    });
    if (!ok) return;
    try {
      this.keys.set(await this.api.deleteApiKey(key.id));
      await this.refreshProviders();
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  private async refreshProviders(): Promise<void> {
    this.providers.set(await this.api.providers());
    if (this.providerConfigured()) this.loadModels();
  }

  protected selectProvider(provider: 'google' | 'openai'): void {
    this.provider.set(provider);
    this.search.set('');
    this.loadModels();
  }

  async loadModels(): Promise<void> {
    this.models.set([]);
    this.modelsError.set(null);
    if (!this.providerConfigured()) {
      this.modelsError.set('Chave de API não configurada para este provedor. Defina-a no arquivo .env.');
      return;
    }
    this.loadingModels.set(true);
    try {
      this.models.set(await this.api.models(this.provider()));
    } catch (error) {
      this.modelsError.set(apiErrorMessage(error));
    } finally {
      this.loadingModels.set(false);
    }
  }

  protected isActive(model: ModelInfo): boolean {
    const settings = this.settings();
    return settings?.llm_provider === model.provider && settings?.llm_model === model.id;
  }

  protected async use(model: ModelInfo): Promise<void> {
    try {
      this.applySettings(await this.api.updateSettings({ llm_provider: model.provider, llm_model: model.id }));
      this.toast.success(`${model.id} agora é o modelo do Mon.`);
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    }
  }

  protected async test(model: ModelInfo): Promise<void> {
    this.tests.update((tests) => ({ ...tests, [model.id]: 'loading' }));
    try {
      const result = await this.api.testModel(model.provider, model.id);
      this.tests.update((tests) => ({ ...tests, [model.id]: result }));
    } catch (error) {
      this.tests.update((tests) => ({
        ...tests,
        [model.id]: { ok: false, latency_ms: null, reply: null, error: apiErrorMessage(error) },
      }));
    }
  }

  protected testResult(id: string): ModelTestResult | 'loading' | undefined {
    return this.tests()[id];
  }

  protected asResult(value: ModelTestResult | 'loading' | undefined): ModelTestResult | null {
    return value && value !== 'loading' ? value : null;
  }

  protected async save(): Promise<void> {
    if (!this.form) return;
    const chunkingChanged =
      this.form.chunk_size !== this.settings()?.chunk_size || this.form.chunk_overlap !== this.settings()?.chunk_overlap;
    this.saving.set(true);
    try {
      this.applySettings(await this.api.updateSettings(this.form));
      this.toast.success('Configurações salvas.');
      if (chunkingChanged) this.toast.info('O novo chunking vale para as próximas indexações. Use "Reindexar tudo" em Jobs.');
    } catch (error) {
      this.toast.error(apiErrorMessage(error));
    } finally {
      this.saving.set(false);
    }
  }

  protected reset(): void {
    const settings = this.settings();
    if (settings) this.form = { ...settings };
  }

  protected formatTokens(value: number | null): string {
    if (!value) return '—';
    return value >= 1_000_000 ? `${value / 1_000_000}M` : `${Math.round(value / 1000)}k`;
  }

  private applySettings(settings: RagSettings): void {
    this.settings.set(settings);
    this.form = { ...settings };
  }
}
