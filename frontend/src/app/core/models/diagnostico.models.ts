/** Tipos do framework de critérios e do diagnóstico (TCC, seções 3.5 a 3.8). */

export type TipoRequisito = 'legal' | 'qualidade' | 'competencia';
export type StatusValidacaoRequisito = 'pendente' | 'aprovado' | 'ajustar';
export type StatusVersao = 'rascunho' | 'em_validacao' | 'validado' | 'arquivado';
export type FormatoOferta = 'presencial' | 'semipresencial' | 'distancia';
export type Classificacao = 'C' | 'PC' | 'NC' | 'EI';
export type CausaDivergencia = 'recuperacao' | 'ocr' | 'chunking' | 'geracao' | 'interpretacao';
export type DiagnosticoStatus =
  | 'planejamento'
  | 'verificando'
  | 'em_validacao'
  | 'validado'
  | 'priorizado'
  | 'relatorio_emitido'
  | 'concluido'
  | 'falhou';

export interface FrameworkVersao {
  id: string;
  versao: string;
  descricao: string;
  data_corte: string | null;
  status: StatusVersao;
  ativa: boolean;
  notas: string | null;
  validado_por: string | null;
  validado_em: string | null;
  created_at: string;
  updated_at: string;
  total_requisitos: number;
  aprovados: number;
}

export interface Requisito {
  codigo: string;
  grupo: string;
  fonte_documento: string;
  fonte_dispositivo: string | null;
  texto: string;
  tipo: TipoRequisito;
  dimensao_inep: number | null;
  indicador_inep: string | null;
  evidencia_esperada: string;
  documentos_provaveis: string[];
  consulta_padrao: string | null;
  termos_chave: string[];
  gravidade_base: number | null;
  peso_dimensao: number | null;
  formatos: FormatoOferta[];
  situacao_normativa: 'vigente' | 'tendencia';
  prazo_referencia: string | null;
  status_validacao: StatusValidacaoRequisito;
  comentario_validacao: string | null;
  ordem: number;
  versao: string | null;
}

export type RequisitoInput = Partial<Omit<Requisito, 'status_validacao' | 'comentario_validacao' | 'versao'>>;

export interface Evidencia {
  n?: number;
  documento: string;
  trecho: string;
  score?: number;
  chunk_id: string;
  pagina: number | null;
  document_id: string | null;
  versao: number | null;
  sha256: string | null;
  ocr: boolean;
  colecao: string | null;
  tipo_documento: string | null;
  localizacao: string | null;
  vector_score?: number | null;
  rerank_score?: number | null;
}

export interface Recuperacao {
  requisito: Requisito;
  consulta: string;
  evidencias: Evidencia[];
  normativos: Evidencia[];
  timings_ms: Record<string, number>;
  config: Record<string, unknown>;
}

export interface Escopo {
  formato_oferta: FormatoOferta | null;
  proximo_ato: 'autorizacao' | 'reconhecimento' | 'renovacao' | 'outro' | null;
  data_ato: string | null;
  incluir_tendencia: boolean;
  tipos: TipoRequisito[];
  grupos: string[];
  codigos: string[];
  validacao_cega: boolean;
  incluir_normativa: boolean;
  observacoes: string | null;
}

export interface DiagnosticoInput {
  nome?: string | null;
  curso?: string | null;
  curso_nome?: string | null;
  framework_versao?: string | null;
  escopo?: Partial<Escopo>;
}

export interface Concordancia {
  n_itens: number;
  n_pares: number;
  n_validados: number;
  percentual_acordo: number | null;
  kappa: number | null;
  kappa_interpretacao: string | null;
  kappa_ponderado_conceito: number | null;
  n_pares_conceito: number;
  matriz_confusao: Record<Classificacao, Record<Classificacao, number>>;
  divergencias_por_causa: Partial<Record<CausaDivergencia, number>>;
  por_tipo: Record<string, { n: number; percentual_acordo: number | null }>;
  distribuicao_proposta: Partial<Record<Classificacao, number>>;
  distribuicao_final: Partial<Record<Classificacao, number>>;
  n_erros: number;
  n_sem_evidencia: number;
  latencia_media_ms: number | null;
  referencia_id: string | null;
}

export interface Diagnostico {
  id: string;
  nome: string;
  curso: string | null;
  curso_nome: string | null;
  escopo: Escopo;
  framework_versao: string;
  config: Record<string, unknown> & { ultima_execucao?: Record<string, unknown> };
  status: DiagnosticoStatus;
  job_id: string | null;
  metricas: Partial<Concordancia>;
  relatorio_emitido_em: string | null;
  devolutiva: { registros?: DevolutivaRegistro[]; ultima?: DevolutivaRegistro };
  referencia_id: string | null;
  created_at: string;
  updated_at: string;
  resumo: {
    total: number;
    propostas: Record<string, number>;
    validados: number;
    classificacao_final: Partial<Record<Classificacao, number>>;
    priorizados: number;
  };
}

export interface PropostaDetalhe {
  classificacao: Classificacao;
  conceito_inep: number | null;
  justificativa: string;
  citacoes: number[];
  lacunas: string[];
  alertas: string[];
  classificacao_original: Classificacao | null;
}

export interface DiagnosticoItem {
  id: string;
  requisito_codigo: string;
  requisito: Partial<Requisito> & { codigo: string; texto: string; tipo: TipoRequisito };
  ordem: number;
  consulta: string | null;
  evidencias: Evidencia[];
  normativos: Evidencia[];
  proposta_status: 'pendente' | 'gerada' | 'erro';
  proposta_oculta: boolean;
  proposta: PropostaDetalhe | null;
  classificacao_proposta: Classificacao | null;
  conceito_proposto: number | null;
  alertas: string[];
  erro: string | null;
  latencia_ms: number;
  gerado_em: string | null;
  classificacao_final: Classificacao | null;
  conceito_final: number | null;
  divergencia_causa: CausaDivergencia | null;
  comentario: string | null;
  validado_em: string | null;
  gut_g: number | null;
  gut_u: number | null;
  gut_t: number | null;
  gut_sugestao: { g?: number; u?: number; motivo_g?: string; motivo_u?: string };
  prioridade: number | null;
}

export interface DevolutivaInput {
  data: string | null;
  participantes: string[];
  resultado: 'aceito' | 'revisado';
  observacoes: string | null;
}

export interface DevolutivaRegistro extends DevolutivaInput {
  relatorio_emitido_em: string | null;
  registrado_em: string;
}

export interface ValidacaoInput {
  classificacao_final: Classificacao;
  conceito_final: number | null;
  divergencia_causa: CausaDivergencia | null;
  comentario: string | null;
}

export const CLASSIFICACOES: { value: Classificacao; label: string; tone: string }[] = [
  { value: 'C', label: 'Conforme', tone: 'success' },
  { value: 'PC', label: 'Parcialmente conforme', tone: 'warning' },
  { value: 'NC', label: 'Não conforme', tone: 'danger' },
  { value: 'EI', label: 'Evidência insuficiente', tone: 'info' },
];

export const CLASSIFICACAO_INFO: Record<Classificacao, { label: string; tone: string }> = Object.fromEntries(
  CLASSIFICACOES.map((c) => [c.value, { label: c.label, tone: c.tone }]),
) as Record<Classificacao, { label: string; tone: string }>;

export const CAUSAS: { value: CausaDivergencia; label: string; hint: string }[] = [
  { value: 'recuperacao', label: 'Recuperação', hint: 'A evidência existe, mas não foi recuperada.' },
  { value: 'ocr', label: 'OCR', hint: 'Texto mal extraído de página digitalizada.' },
  { value: 'chunking', label: 'Divisão em trechos', hint: 'A evidência ficou partida entre trechos.' },
  { value: 'geracao', label: 'Geração', hint: 'O LLM interpretou mal trechos corretos.' },
  { value: 'interpretacao', label: 'Interpretação normativa', hint: 'Divergência de julgamento sobre o requisito.' },
];

export const TIPO_REQUISITO: Record<TipoRequisito, string> = {
  legal: 'Legal',
  qualidade: 'Qualidade (INEP)',
  competencia: 'Competência I4.0',
};

export const STATUS_DIAGNOSTICO: Record<DiagnosticoStatus, { label: string; tone: string }> = {
  planejamento: { label: 'Planejamento', tone: '' },
  verificando: { label: 'Verificando', tone: 'warning' },
  em_validacao: { label: 'Em validação', tone: 'info' },
  validado: { label: 'Validado', tone: 'primary' },
  priorizado: { label: 'Priorizado', tone: 'primary' },
  relatorio_emitido: { label: 'Relatório emitido', tone: 'success' },
  concluido: { label: 'Concluído', tone: 'success' },
  falhou: { label: 'Falhou', tone: 'danger' },
};

/** Etapas do Quadro 9 mostradas no topo do diagnóstico. */
export const ETAPAS: { status: DiagnosticoStatus[]; label: string }[] = [
  { status: ['planejamento'], label: '1. Planejamento' },
  { status: ['verificando', 'falhou'], label: '4. Verificação' },
  { status: ['em_validacao', 'validado'], label: '5. Validação' },
  { status: ['priorizado'], label: '6. Priorização' },
  { status: ['relatorio_emitido'], label: '7. Relatório' },
  { status: ['concluido'], label: '8. Devolutiva' },
];

export const ALERTAS: Record<string, string> = {
  sem_evidencia: 'Nenhum trecho recuperado: EI sem consultar o LLM.',
  sem_citacao: 'O LLM classificou sem citar trechos válidos; rebaixado para EI.',
  citacao_invalida: 'O LLM citou trechos inexistentes (descartados).',
  conceito_descartado: 'Conceito INEP descartado: o requisito não é de qualidade.',
  conceito_ausente: 'O LLM não estimou o conceito INEP.',
};
