-- Open one ex_icc_agent_activity row. Run with getKey=True: id is the first column
-- of ex_icc_agent_activity, so it is the generated key returned.
INSERT INTO ex_icc_agent_activity
    (agent, stage, issue, event, status, summary, detail, prompt)
VALUES
    (:agent, :stage, :issue, :event, :status, :summary, :detail, :prompt)
