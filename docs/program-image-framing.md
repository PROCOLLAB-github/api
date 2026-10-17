# Program image framing

Organizer settings add optional `mobile_cover_image_address` and `image_framing`.
Existing object-scoped manager/staff permissions, atomic lock and
`expected_updated_at` conflict detection remain in effect.

`PATCH /programs/:id/management/settings/basic/` accepts:

```json
{
  "expected_updated_at": "2026-10-17T12:00:00Z",
  "mobile_cover_image_address": "https://example.com/mobile.png",
  "image_framing": {
    "cover": { "x": 50, "y": 50, "zoom": 1 },
    "mobile_cover": { "x": 50, "y": 50, "zoom": 1 },
    "logo": { "x": 50, "y": 50, "zoom": 1 }
  }
}
```

The document is replaced as a whole. All three frames and exactly x/y/zoom are
required when nonempty. x/y are finite numbers in0–100; zoom is finite in1–3.
Booleans, numeric strings, null, unknown/missing keys and non-finite values are400.
`{}` restores centered, unscaled legacy framing. Omitted fields preserve values.
The mobile URL may be empty/null: the client falls back to the main cover, retaining
an independently editable mobile frame. Original image URLs are not rewritten.

Management GET and both public/member detail serializers expose both fields.
Program list exposes `image_framing` so logo cropping stays consistent in cards.
These fields are additive and optional for existing clients; legacy rows default
to `{}` and null. No new permission, endpoint or storage transport is introduced.

Migration0020 adds the two fields. Deploy backend/migration before clients that
write them. Rolling back application code can retain the additive DB columns.

Verification: five framing tests plus management/detail/program regressions on
isolated PostgreSQL; roundtrip/list/member/public, legacy partial writes, reset,
strict invalid documents, finite/bounded numbers, staff/manager and negative roles,
stale409 and absence of partial mutation. Full CI and rollout evidence belong to PR.
