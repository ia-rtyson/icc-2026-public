/**
 * Ignition Issues -- notify Ignition when a card changes column.
 *
 * Fires on every change to the `Stage` field and POSTs the issue id and the new
 * column to the gateway's `issue-stage` WebDev endpoint, which dispatches the
 * agent that owns that column:
 *
 *     Submitted  -> (nobody -- the endpoint ignores it)
 *     Validate   -> Validate Agent   (re-checks the report against the gateway)
 *     Implement  -> Implement Agent  (applies the validated fix)
 *
 * Install: YouTrack -> Administration -> Workflows -> New workflow ->
 * paste this as a rule, then attach the workflow to the "Ignition Issues"
 * project.
 *
 * ENDPOINT uses the gateway's Compose *service* name, because this runs inside
 * the YouTrack container on the same compose network -- `localhost:8088` is the
 * host's view and will not resolve from in there. Use the bare service name
 * (`ignition`), not the project-prefixed container name
 * (`${COMPOSE_PROJECT_NAME}-ignition`): Compose only aliases the container name
 * to the project name actually in effect for that `up`, which varies per
 * deployment (a stack started with `-p demo` is on `demo_net`, where
 * `icc-2026-ignition` does not resolve). The bare service name resolves
 * regardless of project name. A host IP will not do either: it times out from
 * inside the YouTrack container even though it answers from the host or a
 * browser (container-to-host hairpin NAT).
 *
 * If the gateway is not the `ignition` service on the same compose network as
 * YouTrack, change ENDPOINT and re-import this workflow, or the Validate and
 * Implement agents never run.
 */
var entities = require('@jetbrains/youtrack-scripting-api/entities');
var http = require('@jetbrains/youtrack-scripting-api/http');

var ENDPOINT = 'http://ignition:8088/system/webdev/icc-2026/exchange/issue-report/issue-stage';
var TOKEN = 'icc-2026-issue-pipeline';

exports.rule = entities.Issue.onChange({
  title: 'Notify Ignition on Stage change',

  guard: function(ctx) {
    // Only on an actual column move, and only once the field has a value.
    return ctx.issue.fields.isChanged(ctx.Stage) && ctx.issue.fields.Stage !== null;
  },

  action: function(ctx) {
    var stage = ctx.issue.fields.Stage.name;

    var connection = new http.Connection(ENDPOINT, null, 15000);
    connection.addHeader('Content-Type', 'application/json');
    connection.addHeader('X-Pipeline-Token', TOKEN);

    var payload = JSON.stringify({
      issueId: ctx.issue.id,
      stage: stage
    });

    var response = connection.postSync('', [], payload);

    // The endpoint returns 200 for everything (the gateway ignores the
    // status-code key on a python-resource), so branch on the body, not the
    // HTTP status.
    if (!response.isSuccess) {
      console.warn('Ignition stage hook: transport failure for ' + ctx.issue.id +
                   ' -> ' + stage + ': ' + response.statusCode);
      return;
    }

    var body = {};
    try {
      body = JSON.parse(response.response);
    } catch (e) {
      console.warn('Ignition stage hook: unparseable reply for ' + ctx.issue.id +
                   ': ' + response.response);
      return;
    }

    if (body.status === 'accepted') {
      console.log('Ignition stage hook: ' + ctx.issue.id + ' -> ' + stage +
                  ' dispatched to ' + body.agent);
    } else if (body.status === 'ignored') {
      // Expected for Submitted -- filing a ticket should not be noisy.
      console.log('Ignition stage hook: ' + ctx.issue.id + ' -> ' + stage +
                  ' ignored (no agent owns that column)');
    } else {
      console.warn('Ignition stage hook: ' + ctx.issue.id + ' -> ' + stage +
                   ' rejected: ' + response.response);
    }
  },

  requirements: {
    Stage: {
      type: entities.EnumField.fieldType,
      name: 'Stage'
    }
  }
});
