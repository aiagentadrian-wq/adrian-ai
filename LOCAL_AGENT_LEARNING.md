# Local agents: learn, evaluate and report

Use Ollama / the configured local Qwen model for chat and drafting. The application does not fall back to a paid AI service. Local inference is serialized so concurrent requests do not compete for GPU memory. Requests retain their current instructions and supplied evidence; oversized tasks ask for a smaller scope. A model output stopped by its token limit is rejected instead of saved as a completed draft.

## Writer

Add original samples and corrections in Writer Studio. A local model learns sentence length, paragraph length, contractions, short sentences, first-person usage and word complexity. TF-IDF similarity retrieves relevant examples for the draft/review/revision process. Deleting or changing samples rebuilds the model. This is local style learning and retrieval, not fine-tuning Qwen's weights. Three samples are a starting point, not evidence of broad writing quality. Verify facts, citations and assignment requirements. AI-detector results are not an optimization target or a guarantee of authorship.

## Job Finder

Local chat searches installed public feeds without requiring OpenAI web search. Daily job emails still include up to five truthful résumé attachments when a saved résumé is available, or a no-new-results/source-failure update. Confirmed filter matches are prioritized; unverified hours and pay remain labelled. Existing filters and the configured location preferences stay in force.

Save/Skip/I applied on actual saved jobs supplies labelled examples. A regularized logistic-regression model needs at least 20 distinct labelled jobs, at least five of each class, and both classes in chronological training and holdout periods. It ranks jobs only after beating a constant-preference baseline on holdout Brier score. Until then the app uses its original ranking and clearly reports insufficient labels. Changing a choice replaces the previous label for that URL. Scores describe preferences, not the chance of an interview or hiring. No employer applications are sent.

## Paper strategy research

The existing production intraday random forest and multi-horizon swing random forest keep their execution, freshness, loss and promotion checks. They are independent of the chat model. Paper endpoints remain fixed; this update grants no live-money order authority.

A second research lab fits standardized Ridge return models to three rule-defined families: trend breakout, trend pullback and mean reversion, each over three and five sessions. It uses completed daily prices, purges labels crossing chronological training/validation boundaries, freezes the candidate choice on validation, and then shows later-test results and 100-bps cost stress. These labels measure next-open to future-close returns; they are not executable stop/target backtests, combined portfolio returns or actual profit. Historical tests reused on later runs are marked reused.

All six models may create immutable forward shadow forecasts for qualifying completed daily signals. Only subsequent sessions can settle those records. SPY on matching dates is the shadow benchmark. Research rankings never automatically replace the production policy or loosen risk limits. A result of no eligible strategy, a loss or insufficient evidence is reported plainly. A week provides early forward observations; it does not establish a dependable edge or superiority over a human.

## Reports and destination

Routine trading, Manager and learning reports use the saved REPORT_TO inbox through the configured report sender. Gmail approval-proposal threads still go to the authenticated approval owner so reply validation remains valid. The bot's Gmail login and the report recipient are different settings and may legitimately differ.

Reports & Email shows the destination, daily schedule, send claims and acceptance/uncertainty. A daily learning report runs at 18:00 America/Toronto, catches up after a restart that day, and includes actual paper account equity, owned strategy learning, intraday learning, job run status and Writer model status. A final report runs at the existing paper experiment deadline. Open/closed positions and unresolved fills remain explicit; a final report is not a claim that all positions were liquidated. The original experiment is not silently extended or renewed.

The application and internet must remain running; Windows startup tasks alone do not guarantee operation during sleep or shutdown. Persistent claims prevent duplicate sends. A restart during SMTP handoff is marked uncertain and is never blindly retried. A known failure before email handoff can retry. SMTP acceptance proves sender handoff, not inbox delivery. Check the displayed report recipient and receiving inbox; if delivery remains missing after a new routed test, inspect recipient filters or choose the correct address in the saved configuration.

## Evidence and methodological references

Chronological evaluation avoids training on future observations: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html . Trading involves risk of loss; automated or paper results do not promise profit: https://www.investor.gov/additional-resources/spotlight/formerdirectorlorischock-directors-take/thinking-day-trading-know-risks .
