# CM2 `/lab-scan?t=` tablet wiring

QR labels contain only an opaque LDS token in this form:

```text
http://homeassistant.local:8123/lab-scan?t=<scan_token>
```

Create a Lovelace view at path `lab-scan`. Put a Markdown card on it showing `input_text.cm2_selected_name`, `input_select.cm2_pending_action`, and a **Confirm** button that calls `script.cm2_confirm_and_commit`. The scanner must put the token (or the complete URL) into `input_text.cm2_scan_payload`, then call `script.cm2_resolve_scan`. Resolution only arms the 120-second confirmation window; it never writes an LDS event.

## Option 1 — Fully Kiosk Browser URL intent

Configure the scanner app / barcode intent in Fully Kiosk Browser to open the scanned URL directly. Since the payload itself is `/lab-scan?t=<token>`, Fully loads the right Lovelace view. Use a small iframe page or a dashboard card with `browser_mod` to read the query parameter and issue the following two HA service calls in order:

1. `input_text.set_value` for `input_text.cm2_scan_payload`, value = the full current URL (or only `t`);
2. `script.cm2_resolve_scan`.

A `browser_mod` popup/card can then display `input_text.cm2_selected_name` and expose only an explicit **Confirm** action. Do not call `script.cm2_confirm_and_commit` from the URL handler.

## Option 2 — Home Assistant Companion app QR scanner via webhook

Have the Companion app QR scanner or its automation open this LAN-only URL after scanning:

```text
https://<HA external URL>/api/webhook/cm2_lab_scan?t=<scan_token>
```

Then open `/lab-scan` in the app to review and explicitly confirm the resolved record. Add this automation to an HA package (or `automations.yaml`). `webhook_id` must be unique in your HA instance.

```yaml
automation:
  - id: cm2_lab_scan_webhook
    alias: "CM2 · Receive Companion QR token"
    mode: restart
    triggers:
      - trigger: webhook
        webhook_id: cm2_lab_scan
        allowed_methods:
          - GET
          - POST
        local_only: true
    actions:
      - variables:
          token: >-
            {{ trigger.query.t | default(trigger.json.t | default('', true), true) | string | trim }}
      - choose:
          - conditions: "{{ token != '' }}"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.cm2_scan_payload
                data:
                  value: "{{ token }}"
              - action: script.cm2_resolve_scan
          - conditions: []
            sequence:
              - action: persistent_notification.create
                data:
                  title: "CM2 scan webhook ignored"
                  message: "The webhook request did not contain a t token. No LDS record was changed."
```

For both options, use the token exactly as scanned. Never put strain, recipe, dates, weights, operator, or other lab data into the URL.
