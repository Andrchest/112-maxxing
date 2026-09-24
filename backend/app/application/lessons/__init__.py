"""Lesson use cases (HLD `70-i3-alignment.md` §70.3, D15; I3 E4a).

`create_lesson` (every card created at once, one Unit of Work), `start_lesson`, `abort_lesson`,
`release` (the lesson-level report release), `lesson_runner` (starts cards by arrival), `queries`
(`getLesson`, `listLessons`, `listMyIncidents`) and `lesson_report` (the N card reports and their
weighted sum). Lessons emit no events of their own: everything that happens in a card is in that
card's session log.
"""
