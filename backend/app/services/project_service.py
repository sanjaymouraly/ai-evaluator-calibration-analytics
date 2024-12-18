"""Project lifecycle and membership management."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth import require_project_access
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Project, ProjectMember, User
from app.schemas import ProjectCreate, ProjectUpdate

VALID_STATUSES = {"draft", "active", "completed", "archived"}
VALID_PROJECT_ROLES = {"lead", "reviewer", "adjudicator"}


class ProjectService:
    def __init__(self, db: Session):
        self.db = db

    def list_projects(self, user: User, include_archived: bool = False):
        if user.role == "admin":
            q = self.db.query(Project)
        else:
            q = self.db.query(Project).filter(
                (Project.owner_id == user.id)
                | (
                    Project.id.in_(
                        self.db.query(ProjectMember.project_id).filter(ProjectMember.user_id == user.id)
                    )
                )
            )
        if not include_archived:
            q = q.filter(Project.status != "archived")
        return q.order_by(Project.updated_at.desc()).all()

    def get(self, project_id: str, user: User) -> Project:
        project = self._get_or_404(project_id)
        require_project_access(self.db, project, user)
        return project

    def create(self, data: ProjectCreate, owner: User) -> Project:
        if data.disagreement_minor_fraction >= data.disagreement_major_fraction:
            raise ValidationError("minor threshold must be smaller than major threshold.")
        project = Project(**data.model_dump(), owner_id=owner.id)
        self.db.add(project)
        self.db.flush()
        # Owner is implicitly project lead.
        self.db.commit()
        self.db.refresh(project)
        return project

    def update(self, project_id: str, data: ProjectUpdate, user: User) -> Project:
        project = self.get(project_id, user)
        updates = data.model_dump(exclude_unset=True)
        if "status" in updates and updates["status"] not in VALID_STATUSES:
            raise ValidationError(f"status must be one of {sorted(VALID_STATUSES)}")
        for k, v in updates.items():
            setattr(project, k, v)
        self.db.commit()
        self.db.refresh(project)
        return project

    def archive(self, project_id: str, user: User) -> Project:
        project = self.get(project_id, user)
        project.status = "archived"
        self.db.commit()
        self.db.refresh(project)
        return project

    # -- membership --
    def list_members(self, project_id: str, user: User) -> list[ProjectMember]:
        self.get(project_id, user)
        return self.db.query(ProjectMember).filter(ProjectMember.project_id == project_id).all()

    def add_member(self, project_id: str, user_id: str, role_on_project: str, actor: User) -> ProjectMember:
        project = self.get(project_id, actor)
        if role_on_project not in VALID_PROJECT_ROLES:
            raise ValidationError(f"role_on_project must be one of {sorted(VALID_PROJECT_ROLES)}")
        target = self.db.query(User).filter(User.id == user_id).first()
        if target is None or not target.is_active:
            raise NotFoundError("User not found or inactive.")
        existing = (
            self.db.query(ProjectMember)
            .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == user_id)
            .first()
        )
        if existing:
            raise ConflictError("User is already a member of this project.")
        member = ProjectMember(
            project_id=project.id, user_id=user_id, role_on_project=role_on_project, assigned_by=actor.id
        )
        self.db.add(member)
        self.db.commit()
        self.db.refresh(member)
        return member

    def remove_member(self, project_id: str, user_id: str, actor: User) -> None:
        self.get(project_id, actor)  # permission check
        member = (
            self.db.query(ProjectMember)
            .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
            .first()
        )
        if member is None:
            raise NotFoundError("Membership not found.")
        self.db.delete(member)
        self.db.commit()

    def _get_or_404(self, project_id: str) -> Project:
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if project is None:
            raise NotFoundError(f"Project {project_id} not found.")
        return project

    # -- convenience stats used by dashboards --
    def project_progress(self, project: Project) -> dict:
        from app.models import EvaluationTask, Rating

        total = self.db.query(EvaluationTask).filter(EvaluationTask.project_id == project.id).count()
        completed = (
            self.db.query(EvaluationTask)
            .filter(EvaluationTask.project_id == project.id)
            .filter(EvaluationTask.status.in_(["completed", "adjudicated"]))
            .count()
        )
        ratings = (
            self.db.query(Rating)
            .join(EvaluationTask, Rating.task_id == EvaluationTask.id)
            .filter(EvaluationTask.project_id == project.id, Rating.status == "submitted")
            .count()
        )
        reviewers = (
            self.db.query(ProjectMember.user_id)
            .filter(ProjectMember.project_id == project.id)
            .distinct()
            .count()
        )
        return {
            "total_tasks": total,
            "completed_tasks": completed,
            "completion_pct": round(100 * completed / total, 1) if total else 0.0,
            "submitted_ratings": ratings,
            "reviewers": reviewers,
        }
