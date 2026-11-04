"""DynamoDB single-table access. Every key starts with the caller's school and user.

Key layout (see the App data box in the build map):
    SCHOOL#<sid>              PROFILE | POLICY | COURSEMAP#<code>
    SCHOOL#_default           POLICY                       ← PHACT default policy
    SCHOOL#<sid>#USER#<uid>   PROFILE | COURSE#<c> | COURSE#<c>#SYL#v<n> | ANALYSIS#<c>#<aid>
                              EDIT#<aid>#<eid>#V<n> | DECISION#<ts> | SESSION#<aid> | PATTERN#<cat>
    JOB#<id>                  JOB                          ← status, TTL 7 days
    SOURCE#<id>               SOURCE                       ← intake status: in_review → publishing → published | failed; task token
"""


def user_pk(school_id: str, user_id: str) -> str:
    return f"SCHOOL#{school_id}#USER#{user_id}"


def school_pk(school_id: str) -> str:
    return f"SCHOOL#{school_id}"


# TODO: boto3 Table resource from settings.table_name, plus helpers:
#   get_profile, list_courses, put_course, put_syllabus_version, get_policy (falls back to _default),
#   create_job, update_job, get_job, put_analysis, put_edits, set_edit_status, put_decision
