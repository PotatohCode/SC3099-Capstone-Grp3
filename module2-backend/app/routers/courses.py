"""
Course CRUD - see API-SPECIFICATION.md's "Courses" section and
IMPLEMENTATION-PLAN.md's Phase 4.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, get_db, get_optional_user, require_role
from app.core.errors import APIError, ErrorCode
from app.db.models.course import Course
from app.db.models.user import User
from app.schemas.common import Page
from app.schemas.course import CourseCreate, CourseResponse, CourseUpdate
from app.services.audit import log_event
from app.services.authz import require_edit_course
from app.services.sanitize import sanitize_text

router = APIRouter(prefix="/courses", tags=["courses"])


def _to_response(course: Course) -> CourseResponse:
    return CourseResponse(
        id=course.id,
        code=course.code,
        name=course.name,
        description=course.description,
        semester=course.semester,
        instructor_id=course.instructor_id,
        instructor_name=course.instructor.full_name if course.instructor else None,
        venue_name=course.venue_name,
        venue_latitude=course.venue_latitude,
        venue_longitude=course.venue_longitude,
        geofence_radius_meters=course.geofence_radius_meters,
        require_face_recognition=course.require_face_recognition,
        require_device_binding=course.require_device_binding,
        risk_threshold=course.risk_threshold,
        is_active=course.is_active,
        created_at=course.created_at,
    )


@router.get("/", response_model=Page[CourseResponse])
def list_courses(
    is_active: Optional[bool] = Query(default=True),
    semester: Optional[str] = None,
    instructor_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    # Public per tests/public/test_performance.py (list-latency and
    # pagination checks call this with no Authorization header at all and
    # expect 200) - API-SPECIFICATION.md's prose says "Requires auth" but
    # the test wins per IMPLEMENTATION-PLAN.md's own rule.
    query = db.query(Course).options(joinedload(Course.instructor))
    if is_active is not None:
        query = query.filter(Course.is_active == is_active)
    if semester:
        query = query.filter(Course.semester == semester)
    # instructor_id filter is documented admin-only - a non-admin (or
    # anonymous caller) asking for someone else's courses just gets it
    # silently ignored rather than 403'd.
    if instructor_id and current_user is not None and (current_user.role == "admin" or instructor_id == current_user.id):
        query = query.filter(Course.instructor_id == instructor_id)

    total = query.count()
    courses = query.order_by(Course.created_at.desc()).offset(offset).limit(limit).all()
    return Page(items=[_to_response(c) for c in courses], total=total, limit=limit, offset=offset)


@router.get("/{course_id}", response_model=CourseResponse)
def get_course(course_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    course = db.query(Course).options(joinedload(Course.instructor)).filter(Course.id == course_id).first()
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Course not found", ErrorCode.COURSE_NOT_FOUND)
    return _to_response(course)


@router.post("/", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if db.query(Course).filter(Course.code == payload.code).first() is not None:
        raise APIError(status.HTTP_400_BAD_REQUEST, "Course code already exists", ErrorCode.COURSE_CODE_TAKEN)

    course = Course(
        code=payload.code,
        name=payload.name,
        description=sanitize_text(payload.description) if payload.description else None,
        semester=payload.semester,
        instructor_id=payload.instructor_id,
        venue_name=payload.venue_name,
        venue_latitude=payload.venue_latitude,
        venue_longitude=payload.venue_longitude,
        geofence_radius_meters=payload.geofence_radius_meters,
        require_face_recognition=payload.require_face_recognition,
        require_device_binding=payload.require_device_binding,
        risk_threshold=payload.risk_threshold,
    )
    db.add(course)
    db.flush()
    log_event(db, "course_created", user_id=current_user.id, resource_type="course", resource_id=course.id)
    db.commit()
    db.refresh(course)
    return _to_response(course)


@router.put("/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: str,
    payload: CourseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = db.query(Course).options(joinedload(Course.instructor)).filter(Course.id == course_id).first()
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Course not found", ErrorCode.COURSE_NOT_FOUND)
    require_edit_course(current_user, course)

    updates = payload.model_dump(exclude_unset=True)
    if "description" in updates:
        updates["description"] = sanitize_text(updates["description"]) if updates["description"] else None
    for field, value in updates.items():
        setattr(course, field, value)

    log_event(db, "course_updated", user_id=current_user.id, resource_type="course", resource_id=course.id, details=updates)
    db.commit()
    db.refresh(course)
    return _to_response(course)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: str,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    course = db.get(Course, course_id)
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "Course not found", ErrorCode.COURSE_NOT_FOUND)

    course.is_active = False
    log_event(db, "course_deleted", user_id=current_user.id, resource_type="course", resource_id=course.id)
    db.commit()
