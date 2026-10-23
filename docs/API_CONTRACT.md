# RoomSync - API Contract

Version 1.1 · 22 Oct 2026 (first draft agreed 16 Oct 2026)

**Changes since the first draft**

- Endpoints 1 and 2: rules written down (code expiry, one email per minute, 5 tries per code, 8-character passwords).
- Endpoint 3: after 10 wrong logins for one college ID in 15 minutes, that ID is refused for a while.
- Endpoint 18: who can answer and the error cases written down.
- Endpoint 19: new `skipped_dates` list, `end` on each clash, and uploading again replaces the earlier timetable.
- Endpoint 20: readings are sent by the laptop's inference server (not the phone), about every 2.5 seconds.
- Endpoints 24 and 25 added so the dashboard can show names instead of numeric IDs.
- Endpoints 9, 10, 11 and 14: wording corrected to match what the server does.

## Conventions

Every part of RoomSync (dashboard, backend, camera program) follows these rules, so the pieces fit together without renaming anything later.

| Rule | Agreed format | Example |
| --- | --- | --- |
| Base address | All endpoints start with `/api` | `http://<server>:8000/api/bookings` |
| Field names | snake_case, lowercase | `room_id`, `head_count` |
| Dates | `YYYY-MM-DD` | `2026-11-03` |
| Times | 24-hour `HH:MM` | `15:00` |
| Timestamps | ISO 8601 with India time zone | `2026-11-03T15:04:10+05:30` |
| Room IDs | Department + room number | `CSE-101`, `CSE-LAB2` |
| Class IDs | Department + semester + section | `CSE-7A` |
| Logged-in requests | Header `Authorization: Bearer <token>` | Token comes from login |
| Camera program | Header `X-Device-Key: <key>` instead of a login | Key set by admin on the server |

### Fixed values

The backend sends short codes; the dashboard turns them into the labels people see.

| Field | Allowed values | Shown on dashboard as |
| --- | --- | --- |
| `role` | `student`, `teacher`, `admin`, `super_admin` | Student, Teacher, Admin, Super admin |
| `booking_status` | `not_booked`, `scheduled`, `reserved`, `overridden`, `released`, `cancelled` | Not booked, Scheduled, Reserved, Overridden, Released, Cancelled |
| `occupancy` | `people_detected`, `not_detected`, `no_data` | People detected, Not detected, No camera data |
| `camera_status` | `online`, `offline` | — |
| subject `type` | `IPCC`, `PCC`, `PEC`, `OEC`, `PROJ` | Shown as is, like on the college timetable |

CR is not a separate role: it is `"is_cr": true` on a student's account.

### Errors

Every error has the same shape, so the dashboard handles them all the same way:

```json
{ "error": "conflict", "message": "This room is already booked for that time." }
```

| HTTP status | `error` code | When |
| --- | --- | --- |
| 400 | `invalid_input` or `reason_required` | Missing or badly formatted field; admin change with no reason |
| 401 | `not_logged_in` | No token, or token expired |
| 403 | `forbidden` | Logged in, but the role is not allowed to do this |
| 404 | `not_found` | Room, booking or user does not exist |
| 409 | `conflict` | Booking overlaps an existing one (see Bookings) |

## Endpoint summary

32 endpoints cover every flow from the project report (E1 to E9); the sections below give the exact request and reply for each. Endpoints 24 and 25 were added so the dashboard can show names instead of asking for numeric IDs; 26 to 32 for the timetable grid.

| # | Method and path | Who can call it | Purpose | Flow |
| --- | --- | --- | --- | --- |
| 1 | `POST /api/auth/request-setup` | Anyone | Email a one-time setup code to a college ID's email | E1 |
| 2 | `POST /api/auth/set-password` | Anyone with a valid code | Set password on first login | E1 |
| 3 | `POST /api/auth/login` | Anyone | Log in, get a token | E1 |
| 4 | `GET /api/auth/me` | Logged in | Current user's details | E1 |
| 5 | `POST /api/admin/admins` | Super admin | Give a teacher admin rights | E1 |
| 6 | `DELETE /api/admin/admins/{user_id}` | Super admin | Remove admin rights | E1 |
| 7 | `PUT /api/classes/{class_id}/cr` | That class's teacher | Mark or clear the CR | E6 |
| 8 | `GET /api/rooms` | Logged in | List all rooms | E2 |
| 9 | `GET /api/rooms/status` | Logged in | Every room's booking status and occupancy for a slot | E2 |
| 10 | `GET /api/rooms/{room_id}/schedule` | Logged in | One room's bookings for a day | E2 |
| 11 | `POST /api/rooms` | Admin | Add a room | — |
| 12 | `POST /api/bookings` | Teacher, admin | Reserve a room | E3, E4 |
| 13 | `GET /api/bookings/mine` | Teacher, admin | My bookings | E9 |
| 14 | `DELETE /api/bookings/{booking_id}` | Teacher who booked it | Cancel own reservation | E9 |
| 15 | `POST /api/bookings/{booking_id}/override` | Admin | Take over a booking's slot, with reason | E5 |
| 16 | `POST /api/bookings/{booking_id}/reschedule` | Admin | Move a booking, with reason | E5 |
| 17 | `POST /api/bookings/{booking_id}/remove` | Admin | Remove a booking, with reason | E5 |
| 18 | `POST /api/bookings/{booking_id}/no-show-response` | Teacher who booked it, class CR | Answer the no-show reminder: keep or release | E8 |
| 19 | `POST /api/timetable` | Admin | Upload weekly timetable entries | E6 |
| 20 | `POST /api/occupancy` | Camera program (device key) | Send a people-detection result | E7 |
| 21 | `GET /api/occupancy/{room_id}` | Logged in | Latest reading for one room | E7 |
| 22 | `GET /api/notifications` | Logged in | My notifications | E5, E8 |
| 23 | `POST /api/notifications/{id}/read` | Logged in | Mark a notification as read | E5, E8 |
| 24 | `GET /api/users` | Admin, super admin | List people (e.g. teachers) by name | E1, E6 |
| 25 | `GET /api/classes/mine` | Teacher, admin | Classes I am class teacher of, with students | E6 |
| 26 | `GET /api/periods` | Logged in | The timetable grid's days and periods | E6 |
| 27 | `GET /api/subjects` | Logged in | The course list | E6 |
| 28 | `GET /api/classes` | Logged in | Every class with its timetable-sheet details | E6 |
| 29 | `POST /api/subjects` | Admin | Add a subject | E6 |
| 30 | `GET /api/teaching` | Logged in | Who teaches which subject to which class | E6 |
| 31 | `POST /api/teaching` | Admin | Record who teaches what | E6 |
| 32 | `DELETE /api/teaching/{teaching_id}` | Admin | Remove a teaching assignment | E6 |

## Accounts and login

Accounts already exist (imported from college ID records), so first login is just setting a password with a code sent to the user's college email.

### 1. Request a setup code

`POST /api/auth/request-setup`

```json
{ "college_id": "1JS23CS044" }
```

Reply `200`, always the same so nobody can test which IDs exist:

```json
{ "message": "If this ID exists, a setup code has been sent to its college email." }
```

### 2. Set password

`POST /api/auth/set-password`

```json
{ "college_id": "1JS23CS044", "code": "483920", "new_password": "at-least-8-chars" }
```

Reply `200` `{ "message": "Password set. You can now log in." }`. Wrong or expired code: `400 invalid_input`.

Rules: the code is 6 digits, stored hashed, expires after 15 minutes and works once. Asking for a new code cancels the old one, and at most one code is emailed per minute per account. After 5 wrong tries a code stops working (ask for a new one). `new_password` must be at least 8 characters (`400 invalid_input`, which does not count as a wrong try). An unknown ID gets the same `400` as a wrong code. The same two endpoints also work to reset a forgotten password.

### 3. Log in

`POST /api/auth/login`

```json
{ "college_id": "1JS23CS044", "password": "at-least-8-chars" }
```

Reply `200`:

```json
{
  "token": "eyJhbGciOi...",
  "user": {
    "user_id": 12,
    "college_id": "1JS23CS044",
    "name": "Deeptanshu Pandey",
    "email": "1js23cs044@college-domain.example",
    "role": "student",
    "department": "CSE",
    "class_id": "CSE-7A",
    "is_cr": false
  }
}
```

Wrong ID or password: `401 not_logged_in` with the same message for both.

After 10 wrong logins for one college ID within 15 minutes, that ID gets `401 not_logged_in` with the message "Too many failed logins for this ID. Try again in N minutes, ..." even with the right password, until the oldest of those tries is 15 minutes old. This applies to made-up IDs too, so it reveals nothing. A successful login, or setting a new password with a setup code (endpoints 1, 2), clears the count.

### 4. Current user

`GET /api/auth/me` returns the same `user` object as login.

### 5 and 6. Grant or remove admin rights (super admin)

`POST /api/admin/admins` with `{ "user_id": 31 }`, reply `200` with the updated `user`. Only teachers can be made admins; anyone else gets `400 invalid_input`.

`DELETE /api/admin/admins/31`, reply `200` with the updated `user`.

### 7. Set a class CR (class teacher)

`PUT /api/classes/CSE-7A/cr`

```json
{ "student_id": 12 }
```

Send `{ "student_id": null }` to clear the CR. Reply `200`:

```json
{ "class_id": "CSE-7A", "cr": { "user_id": 12, "name": "Deeptanshu Pandey" } }
```

## Rooms

The room-status endpoint is what the dashboard grid is built on; each room comes back with booking status and occupancy as separate fields.

### 8. List rooms

`GET /api/rooms`, optional filters `?building=Main&type=lab`. Reply `200`:

```json
[
  {
    "room_id": "CSE-101",
    "name": "CSE Classroom 101",
    "type": "classroom",
    "building": "Main",
    "floor": 1,
    "capacity": 60,
    "department": "CSE",
    "has_camera": true
  }
]
```

`type` is one of `classroom`, `lab`, `meeting_room`.

### 9. Room status for a slot

`GET /api/rooms/status?date=2026-11-03&start=15:00&end=16:00`, optional `&building=Main`. Reply `200`:

```json
[
  {
    "room_id": "CSE-101",
    "name": "CSE Classroom 101",
    "type": "classroom",
    "booking_status": "reserved",
    "booking": {
      "booking_id": 87,
      "booked_by": { "user_id": 5, "name": "Prof. A. Sharma" },
      "purpose": "Extra class - DBMS",
      "class_id": "CSE-7A",
      "date": "2026-11-03",
      "start": "15:00",
      "end": "16:00"
    },
    "occupancy": "people_detected",
    "head_count": 23,
    "last_reading_at": "2026-11-03T15:04:10+05:30"
  },
  {
    "room_id": "CSE-102",
    "name": "CSE Classroom 102",
    "type": "classroom",
    "booking_status": "not_booked",
    "booking": null,
    "occupancy": "not_detected",
    "head_count": 0,
    "last_reading_at": "2026-11-03T15:04:08+05:30"
  }
]
```

Occupancy is the latest reading, so it is only meaningful for the current time. For a slot that does not include the current time (past or future), `occupancy`, `head_count` and `last_reading_at` are `null`. `end` must be after `start` (`400 invalid_input`).

### 10. One room's schedule

`GET /api/rooms/CSE-101/schedule?date=2026-11-03`. Reply `200`: a list of booking objects (see "The booking object" below) for that day, in time order. Only active bookings (`scheduled`, `reserved`) are listed. Unknown room: `404 not_found`.

### 11. Add a room (admin)

`POST /api/rooms` with the same fields as endpoint 8, plus `"camera_stream": "rtsp://..."` if the room has a camera. Reply `201` with the room. The camera stream address is never sent back to the dashboard; the room shows `"has_camera": true` instead. `room_id` is stored in capitals and may only contain letters, numbers and dashes (2-20 characters). A room that already exists gives `400 invalid_input`.

## Bookings

One `booking` object is used everywhere; a `409 conflict` reply carries everything the dashboard needs to show the "already booked" pop-up.

### The booking object

```json
{
  "booking_id": 87,
  "room_id": "CSE-101",
  "date": "2026-11-03",
  "start": "15:00",
  "end": "16:00",
  "purpose": "Extra class - DBMS",
  "class_id": "CSE-7A",
  "booking_status": "reserved",
  "booked_by": { "user_id": 5, "name": "Prof. A. Sharma" },
  "created_at": "2026-10-30T10:12:00+05:30"
}
```

`class_id` is optional (`null` for a meeting). When it is set, that class's CR gets notifications about this booking.

### 12. Reserve a room

`POST /api/bookings`

```json
{
  "room_id": "CSE-101",
  "date": "2026-11-03",
  "start": "15:00",
  "end": "16:00",
  "purpose": "Extra class - DBMS",
  "class_id": "CSE-7A"
}
```

Reply `201` with the new booking object (`booking_status: "reserved"`).

If the slot overlaps an existing booking, reply `409`:

```json
{
  "error": "conflict",
  "message": "This room is already booked for that time.",
  "existing_booking": {
    "booking_id": 64,
    "booking_status": "scheduled",
    "booked_by": { "user_id": 9, "name": "Prof. R. Rao" },
    "purpose": "Computer Networks",
    "date": "2026-11-03",
    "start": "14:30",
    "end": "15:30"
  },
  "free_rooms": [
    { "room_id": "CSE-102", "name": "CSE Classroom 102" },
    { "room_id": "CSE-LAB2", "name": "CSE Lab 2" }
  ]
}
```

Other rules: `end` must be after `start` and the date cannot be in the past (`400 invalid_input`); students get `403 forbidden`. Back-to-back bookings (one ends at 15:00, the next starts at 15:00) are allowed.

### 13. My bookings

`GET /api/bookings/mine`, optional `?from=2026-11-01&to=2026-11-30`. Reply `200`: a list of booking objects.

### 14. Cancel own reservation

`DELETE /api/bookings/87`. Reply `200` with the booking, now `"booking_status": "cancelled"`. Only the teacher who made it can cancel; anyone else gets `403 forbidden`. Timetable classes (`scheduled`) can only be changed by an admin (`403 forbidden`), and a booking that is no longer `reserved` gives `400 invalid_input`.

### 15. Override (admin)

`POST /api/bookings/87/override`: the admin takes the same room and time for their own purpose.

```json
{ "purpose": "Placement drive briefing", "class_id": null, "reason": "Company visit moved to today" }
```

Reply `200`:

```json
{
  "old_booking": { "booking_id": 87, "booking_status": "overridden" },
  "new_booking": { "booking_id": 112, "booking_status": "reserved" },
  "notified": ["Prof. A. Sharma", "CR of CSE-7A"]
}
```

### 16. Reschedule (admin)

`POST /api/bookings/87/reschedule`

```json
{ "room_id": "CSE-102", "date": "2026-11-03", "start": "15:00", "end": "16:00", "reason": "CSE-101 projector under repair" }
```

Reply `200` with the updated booking and the `notified` list. If the new slot is taken, `409 conflict` as in endpoint 12.

### 17. Remove (admin)

`POST /api/bookings/87/remove` with `{ "reason": "Department event in this room" }`. Reply `200` with the booking, now `"booking_status": "cancelled"`, and the `notified` list.

For endpoints 15 to 17, a missing or empty `reason` gives `400 reason_required`, and non-admins get `403 forbidden`. Every call writes a change-log entry.

### 18. Answer a no-show reminder

`POST /api/bookings/87/no-show-response`

```json
{ "action": "keep" }
```

`action` is `keep` or `release`. Reply `200` with the booking: unchanged for `keep`, or `"booking_status": "released"` for `release`. Only the teacher who booked it or that class's CR can answer (others: `403 forbidden`). After `keep`, the no-show check leaves the booking alone; after `release`, the other person is notified with `booking_released`. A booking with no reminder sent, one that is no longer active, or one that has ended gives `400 invalid_input`.

## Timetable, occupancy and notifications

The camera program only ever calls endpoint 20; everything it sends is a yes/no and a number, never an image.

### 19. Upload timetable (admin)

`POST /api/timetable`

```json
{
  "semester_start": "2026-08-18",
  "semester_end": "2026-12-05",
  "entries": [
    {
      "room_id": "CSE-101",
      "class_id": "CSE-7A",
      "teacher_id": 9,
      "subject": "Computer Networks",
      "weekday": "tuesday",
      "start": "14:30",
      "end": "15:30"
    }
  ]
}
```

Reply `200`:

```json
{
  "scheduled_bookings_created": 14,
  "clashes": [
    { "room_id": "CSE-LAB2", "weekday": "monday", "start": "09:00", "end": "11:00", "entries": ["CSE-7A Networks Lab", "CSE-5B DBMS Lab"] }
  ],
  "skipped_dates": [
    {
      "room_id": "CSE-101",
      "date": "2026-11-03",
      "start": "14:30",
      "end": "15:30",
      "entry": "CSE-7A Computer Networks",
      "existing_booking": {
        "booking_id": 87,
        "booking_status": "reserved",
        "booked_by": { "user_id": 5, "name": "Prof. A. Sharma" },
        "purpose": "Extra class - DBMS",
        "date": "2026-11-03",
        "start": "15:00",
        "end": "16:00"
      }
    }
  ]
}
```

Each entry becomes one `scheduled` booking per week from `semester_start` to `semester_end` (only dates that have not started yet). Its `purpose` is the `subject`, booked by `teacher_id` for `class_id`.

- `clashes`: entries in this upload that need the same room at the same time. **None of them is saved**; the admin fixes them and uploads again. `start`/`end` cover the whole clash.
- `skipped_dates`: weeks where the room is already booked. The entry's other weeks are saved; only these dates are skipped. `existing_booking` has the same shape as in the `409` "already booked" reply, so an admin can decide what to move.
- People detected by a camera never block a timetable entry.

Uploading again for an overlapping semester **replaces** the earlier timetable: its classes that have not started yet are removed (or marked `cancelled` if an admin had already changed them) and rebuilt from the new upload. Past classes stay.

Errors: any unknown room, class or teacher (`404 not_found`), a `teacher_id` that is not an active teacher or admin, `end` not after `start`, a bad `weekday`, `semester_end` before `semester_start`, a semester longer than a year, or no entries (`400 invalid_input`) reject the whole upload and nothing changes. Teachers and students get `403 forbidden`.

### 20. Send a people-detection result (camera program)

`POST /api/occupancy` with header `X-Device-Key: <key>`

```json
{
  "room_id": "CSE-101",
  "people_detected": true,
  "head_count": 23,
  "camera_status": "online",
  "time": "2026-11-03T15:04:10+05:30"
}
```

Reply `201` `{ "received": true }`. Sent by the inference server on the laptop after each frame the phone sends (about every 2.5 seconds per room), so the device key never leaves the laptop. If the camera cannot be read, send `"camera_status": "offline"`, `"people_detected": null` and `"head_count": null`.

Checks (`400 invalid_input`): an `online` reading needs `people_detected` true or false; `false` needs `head_count` 0, `true` needs 1 or more (or `null`); `time` cannot be more than 2 minutes in the future. Wrong or missing device key: `401 not_logged_in`. Unknown `room_id`: `404 not_found`. A time without a zone is read as India time.

### 21. Latest reading for a room

`GET /api/occupancy/CSE-101`. Reply `200`:

```json
{ "room_id": "CSE-101", "occupancy": "people_detected", "head_count": 23, "last_reading_at": "2026-11-03T15:04:10+05:30" }
```

If the last reading is over 1 minute old or the camera is offline, `occupancy` is `no_data`.

### 22. My notifications

`GET /api/notifications`, optional `?unread=true`. Reply `200`:

```json
[
  {
    "notification_id": 301,
    "type": "booking_overridden",
    "message": "Your booking of CSE-101 on 3 Nov, 15:00-16:00 was taken over by Dr. K. Rao (HOD). Reason: Company visit moved to today.",
    "booking_id": 87,
    "read": false,
    "created_at": "2026-11-03T11:20:00+05:30"
  }
]
```

`type` is one of `booking_overridden`, `booking_rescheduled`, `booking_removed`, `no_show_reminder`, `booking_released`. Each one is also sent by email.

### 23. Mark as read

`POST /api/notifications/301/read`. Reply `200` `{ "notification_id": 301, "read": true }`. Users can only mark their own notifications.

## People and classes

### 24. List people (admin, super admin)

`GET /api/users`, optional `?role=teacher` (any `role` value). Reply `200`, active users sorted by name:

```json
[
  { "user_id": 9, "college_id": "T003", "name": "Prof. R. Rao", "role": "teacher", "department": "CSE" }
]
```

Used to pick a teacher to make an admin, and to turn college IDs in a timetable file into `teacher_id`s. Others get `403 forbidden`.

### 25. My classes (teacher, admin)

`GET /api/classes/mine`. Reply `200`: the classes the caller is class teacher of, each with its active students sorted by name. An empty list means the caller is not a class teacher.

```json
[
  {
    "class_id": "CSE-7A",
    "name": "CSE 7th sem A",
    "department": "CSE",
    "students": [
      { "user_id": 12, "college_id": "1JS23CS044", "name": "Deeptanshu Pandey", "is_cr": true }
    ]
  }
]
```

Students and the super admin get `403 forbidden`.

### 28. Class list (logged in)

`GET /api/classes`. Reply `200`, every class sorted by ID, with what the timetable sheet's header shows. Every field after `department` may be `null`.

```json
[
  {
    "class_id": "CSE-7A",
    "name": "CSE 7th sem A",
    "department": "CSE",
    "semester_label": "VII-A",
    "home_room_id": "A-312",
    "strength": 64,
    "wef_date": "2026-07-20",
    "class_teacher": { "user_id": 5, "name": "Prof. A. Sharma" }
  }
]
```

`strength` is the number of students, used to suggest rooms that are big enough. `wef_date` is "with effect from", the date the class's timetable starts.

## Periods, subjects and who teaches what

The timetable grid is drawn from these, so no times or course names are typed into the dashboard.

### 26. Periods (logged in)

`GET /api/periods`. Reply `200`: the grid's rows (`days`) and columns (`periods`) in order. The lunch break is included so the grid can show it, with `bookable: false`.

```json
{
  "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"],
  "periods": [
    { "period": "P1", "label": "P1", "start": "09:00", "end": "10:00", "bookable": true },
    { "period": "P2", "label": "P2", "start": "10:00", "end": "11:00", "bookable": true },
    { "period": "P3", "label": "P3", "start": "11:00", "end": "12:00", "bookable": true },
    { "period": "P4", "label": "P4", "start": "12:00", "end": "13:00", "bookable": true },
    { "period": "lunch", "label": "Lunch break", "start": "13:00", "end": "13:45", "bookable": false },
    { "period": "P5", "label": "P5", "start": "13:45", "end": "14:45", "bookable": true },
    { "period": "P6", "label": "P6", "start": "14:45", "end": "15:45", "bookable": true },
    { "period": "P7", "label": "P7", "start": "15:45", "end": "16:45", "bookable": true }
  ]
}
```

### 27. Subjects (logged in)

`GET /api/subjects`. Reply `200`, sorted by code:

```json
[
  { "code": "BCS702", "title": "Parallel Computing", "type": "IPCC", "credits": 4, "department": "CSE" }
]
```

### 29. Add a subject (admin)

`POST /api/subjects` with the same fields as one item of endpoint 27. `code` is letters, digits and `-` only, stored in capitals. `credits` is 0 to 30. Reply `201` with the subject.

Errors: a code that already exists (`409 conflict`), a bad `type` or other field (`400 invalid_input`). Others get `403 forbidden`.

### 30. Who teaches what (logged in)

`GET /api/teaching`, optional `?teacher=T002` (a college ID) and/or `?class_id=CSE-7A`. Reply `200`, sorted by class, subject code, then batch (whole class first):

```json
[
  {
    "teaching_id": 3,
    "teacher": { "user_id": 5, "college_id": "T002", "name": "Prof. A. Sharma", "initials": "AS" },
    "subject": { "code": "BCS702", "title": "Parallel Computing", "type": "IPCC", "credits": 4, "department": "CSE" },
    "class_id": "CSE-7A",
    "batch": null
  }
]
```

Rows are added automatically by the timetable upload (endpoint 19) and by admins (endpoint 31). Students use it for the course table under their timetable; teachers can only book extra classes for subjects they have a row for.

### 31. Record who teaches what (admin)

`POST /api/teaching`

```json
{ "teacher": "T002", "subject_code": "BCS702", "class_id": "CSE-7A", "batch": null }
```

Give the teacher as `teacher` (college ID) or `teacher_id`, not both. `batch` is optional. Reply `201` with the row, as in endpoint 30.

Errors: unknown teacher, subject or class (`404 not_found`), someone who is not an active teacher or admin, or both/neither teacher fields (`400 invalid_input`), the same teacher, subject, class and batch already recorded (`409 conflict`). Others get `403 forbidden`.

### 32. Remove a teaching assignment (admin)

`DELETE /api/teaching/{teaching_id}`. Reply `200` with the removed row. Timetable classes already created are not changed. Unknown ID: `404 not_found`. Others get `403 forbidden`.
