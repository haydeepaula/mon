import uuid

from fastapi import APIRouter, status

from app.api.deps import AdminUser, DbSession
from app.api.schemas.evals import (
    EvalCaseIn,
    EvalCaseOut,
    EvalFromFramework,
    EvalGenerateRequest,
    EvalImportRequest,
    EvalRunCreate,
    EvalRunDetailOut,
    EvalRunOut,
)
from app.api.schemas.jobs import JobOut
from app.services.eval_service import EvalService

router = APIRouter(prefix="/evals", tags=["Avaliação"])


@router.get("/cases", response_model=list[EvalCaseOut])
def list_cases(_: AdminUser, db: DbSession):
    return EvalService(db).list_cases()


@router.post("/cases", response_model=EvalCaseOut, status_code=status.HTTP_201_CREATED)
def create_case(body: EvalCaseIn, _: AdminUser, db: DbSession):
    case = EvalService(db).create_case(body.model_dump())
    db.commit()
    return case


@router.put("/cases/{case_id}", response_model=EvalCaseOut)
def update_case(case_id: uuid.UUID, body: EvalCaseIn, _: AdminUser, db: DbSession):
    case = EvalService(db).update_case(case_id, body.model_dump())
    db.commit()
    return case


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(case_id: uuid.UUID, _: AdminUser, db: DbSession):
    EvalService(db).delete_case(case_id)
    db.commit()


@router.post("/cases/import", response_model=dict[str, int])
def import_cases(body: EvalImportRequest, _: AdminUser, db: DbSession):
    imported = EvalService(db).import_cases([case.model_dump() for case in body.cases])
    db.commit()
    return {"imported": imported}


@router.post("/cases/from-framework", response_model=dict[str, int])
def cases_from_framework(body: EvalFromFramework, _: AdminUser, db: DbSession):
    """Cria um caso por requisito do framework (consulta padronizada como pergunta)."""
    created = EvalService(db).cases_from_framework(body.versao, body.tipos)
    db.commit()
    return {"created": created}


@router.post("/cases/generate", response_model=JobOut)
def generate_cases(body: EvalGenerateRequest, user: AdminUser, db: DbSession):
    return EvalService(db).enqueue_generation(body.count, user.id)


@router.get("/runs", response_model=list[EvalRunOut])
def list_runs(_: AdminUser, db: DbSession):
    return EvalService(db).list_runs()


@router.post("/runs", response_model=EvalRunOut, status_code=status.HTTP_201_CREATED)
def start_run(body: EvalRunCreate, user: AdminUser, db: DbSession):
    run = EvalService(db).start_run(body.name, body.case_ids, user.id, body.modo, body.curso)
    db.commit()  # o job e a execução precisam existir antes de o cliente consultar
    return run


@router.get("/runs/{run_id}", response_model=EvalRunDetailOut)
def get_run(run_id: uuid.UUID, _: AdminUser, db: DbSession):
    return EvalService(db).get_run(run_id)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: uuid.UUID, _: AdminUser, db: DbSession):
    EvalService(db).delete_run(run_id)
    db.commit()
