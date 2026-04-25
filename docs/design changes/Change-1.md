# Change-1

Part-1: Web Application UI/UX

- Home — Predict Tab:
    - Add the architecture diagram to Streamlit interface in pipeline status tab.
    - The model predictions are inconsistent, whats the issue? “Zomato food delivery” gets predicted as “Shopping & Retail” whereas the correct category is “Food & dining”
    - Using streamlit, unable to select the models logged into mlflow artifacts using a dropdown UI, unable to hotswap to any previous training run.
    - When clicking on example buttons, I am unable to copy the text. I’d Ideally want that once I click on example buttons, the text should get copied to the ‘transaction description’ textbox. I can later click classify by myself.
- Batch Predict Tab:
    - The following text have inconsistent classification in batch predict, fix it!:
        - Zomato food delivery
        - BESCOM electricity bill
    - Hovering over the predicted table gives an option to download the csv. However, I’d want an additional button below the table which appears once batch prediction is done and allows to download the same csv.
    - I have a batch transaction data in data/batch/batch_raw folder by the name batch.xls. This is basically the past 1month statement of my HDFC bank account exported in raw format. I want you to analyse the file, it’s structure and arrangement of data columns within it. There are columns within the the data as : [Date, Narration, Withdrawal Amt.] and several other columns are also present. For our purpose only the columns Narration & Withdrawal Amt. are important. The Narration corresponds to the description column in our original training dataset whose categories we have to predict. Now, in the streamlit UI, the batch predict page where we upload the raw file (Upload CSV), I want you to allow upload an xls file (having the same format as batch.xls), prepare a python script that processess the xls file after UI upload and saves a new csv file with description column whose values are nothing but the narration column in the xls file above, also prepare a second column by the name ‘amount’ which has the corresponding Withdrawal Amt. data from above. Now, as a follow up, the UI xls upload functionality should use this newly saved csv file to carry out batch prediction of the transactions (using the processed batch file above) and save a new csv file in the same directory with (description, amount, category) where the category columns is the predicted class for description predicted using our model. After this in the UI, display a formal message something like “Batch Data Processed — Collection Statistics send to email”. As a follow up, an email should be sent to my configured email ID which shows a pie chart of transactions (aggregating the Withdrawal Amt.) by category and a table denoting the predicted category and % of aggregate withdrawal amount by predicted category. I also have folders like data/batch/batch_processed
- Pipeline status Tab:
    - I’d like to see the health statuses of prometheus, pushgateway and alertmanager as well
    - pipeline status should have the following diagrams
        - Architecture diagram
        - HLD pipeline
    - should have direct links to all the other 7 services UIs for deeper inspection

Part-2: API layer

- FAST API Swagger:
    - The following functionality is not actually working:
        - Listing of all MLflow runs available for model switching — run_id, F1 score, timestamp.
        - The frontend is unable to populate the model selection dropdown.
    - Regarding POST/feedback, this a good feature to have for feedback loop. However, I’d like to bring this feature forth to the UI (Home — Predict) page. I Input a string, if the predicted classification doesnt feel right to me then allow me to select the correct class in the UI itself and a button (to click) that would record this as a new data point in feedback.jsonl.
    - There should be a minimum sample threshold of 100 samples for /drift for it to show a flag. These feedback samples are stored in feedback.jsonl and the distribution will be calculated using feedback_norm, is that correct?
    - Split the data/raw/transactions.csv into 2 datasets (90-10 split). These datasets should have a drifted distribution of class labels. I.e. The 10% data must be drifted from the other 90% data. The reason for doing this is that I want to mock the run of complete airflow dag which will happen if it encounters a drift in the 10% data (which acts as real world drifted data). The moment airflow dag senses the drift in 10% data from the actual 90% dataset, It runs the dvc pipeline and uses the already trained model which was obtained on the previous dvc pipeline run within the same GitHub Job-2. The retraining must happen using the models weights already saved from the previous dvc training (within the same run) and should happen for 1 epoch using the combined data (90%+10%). I hope you understand my Idea. By this token every time we trigger a Github Actions run, dvc pipeline will be run twice. first, using the 90% dataset and second, using the drifted (10%) dataset + earlier 90% dataset. This 10% dataset must be stored in a folder that is polled by airflow every 24 hours. To this 10% dataset, you will also append the corrected data extracted and converted as (description, actual_category) pairs from feedback.jsonl and then this augmented 10% will go onto merge with remaining 90% data for retraining purpose we described earlier. The feedback.jsonl should persist accross GitHub Actions re-run. Ensure that feedback.jsonl persists overall and any corrected class predictions are appended to it rather than being overwritten. So in the entire pipeline, across multiple runs, the 90% data and 10% data (which drifts) will remaining fixed, while the feedback.jsonl keeps changing and is the source of data variation in the overall training.
    - The Get /drift should be executed when there are at least 100 data points and drift is detected wrt the baseline.

Part-3: MLFlow Experiment Tracking

    - The evaluate run artifacts in MLFlow has confusion matrix as json, also upload the confusion matrix as heatmap viz.
    - As stated above, in mlflow, log the model obtained as a result of 1st dvc pipeline run (90%) and also log the model as a result of Airflow triggered 2nd dvc pipeline run (90%+10%+feedback.jsonl). As I described it above, the 1st dvc pipeline run and 2nd dvc pipeline run (tiggered by airflow dag) should be within the same GitHub run. The final model trained on 90%+10%+feedback.jsonl should be served on the streamlit UI.
    - the auto registry promotion feature should be retained

Part-4: Airflow Data Pipeline
    - Here is the current airflow dag: verify_raw_data → validate_schema → check_nulls → check_drift → run_ingest → trigger_dvc. I want you to make some changes to the DAG, add a task at the end of the pipeline by the name pipeline_complete. Create 2 edges edge from the check_drift,
        - (the first edge) if no drift detected then directly route to pipeline_complete,
        - (the second edge) if drift detected then take the normal course.
        - In whichever case, the pipeline run gets complete.
    - As described above, in Job-2 of a GitHub Actions run, the dvc pipeline is triggerred first with 90% of the data derived from /data/ingested/transactions.csv. After this when Airflow Dag Runs, it combines the remaining 10% data which is appended with the data processed and obtained from feedback.jsonl. The 90-10 split is done such that there is a drift (of 10% data) from the original (90%) data, the amount of this drift is enough to trigger the remaining run_ingest, trigger_dvc.

Part-6: Prometheus+Grafana
    - In grafana remove the panel for error rate. The model loaded should “Model Loaded” instead of “1”.
    - The panels for Training Val F1 (Macro), Test F1 Macro, Test Accuracy should be removed and Training duration (It says “No Data”. You should fix it.) be retained.

Part-7:
    - Model selection dropdown is not working and I am unable to switch the model to a different run ID. Make the hotswap work on streamlit interface.

Miscellaneous: Prometheus, PushGateway, Graphana, AlertManager:
    - Ensure that the following metrics persist: **`spendsense_feedback_total, spendsense_drift_score, spendsense_predictions_by_category_total, spendsense_requests_total, spendsense_batch_size`**
    - For alert manager: Add scrape target alertmanager:9093/metrics — gives alertmanager_alerts_fired_total, alertmanager_notifications_total, alertmanager_silences. These metrics must be tracked and plot alerts_fired_total into Grafana DB that must persist accross several docker builds.
    - Log the per-container CPU/memory/disk usage in a single plot in Grafana Dashboard
    - Add additional metrics from FastAPI
        - spendsense_model_switches_total
        - spendsense_feedback_total
    - In the graphana dashboard:
        - Add a latency heatmap
        - Add a single panel which shows the status if all the remaining 7 services are up or not
        - A single panel for total alerts fired per category
        - A panel containing table of alerts fired in last 15m chronologically
        - Add a panel to display which stage/job of CI run is active. There a 3 jobs, the panel should show the active job in orange color (active) with time elapsed so far. The completed job should be shown in green color (completed) with time taken. The job which as not been taken up yet should be shown in grey color. All of this must happen with a same panel. This will happen only when I invoke the grafana db when a CI run is active. But later when I open the grafana db interface, all jobs must have completed, in that case I should be able to see all the jobs in green, the plots are logged pertaining to the last CI run.
    - I should receive alerts for the following:
        - Whenever a run is triggered on GitHub Actions
        - Whenever a job passes in a run
        - Whenever a run is complete
        - High CPU usage
        - Inference latency anomaly