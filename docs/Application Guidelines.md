# Guidelines

## Guidelines: Building an AI Application with MLOps

This document outlines guidelines for building AI applications that strictly adhere to MLOps principles and follow best practices for the AI product lifecycle. It aims to ensure efficient, scalable, reliable, and maintainable AI solutions.

## I. Core Principles:

- Automation: Automate all stages of the ML lifecycle, from data ingestion and preprocessing to model training, evaluation, deployment, and monitoring.
- Reproducibility: Ensure that every step of the process can be easily reproduced, allowing for experimentation, debugging, and rollback. Every experiment must be reproducible via a specific Git commit hash and a corresponding MLflow run ID.
- Continuous Integration (CI): Implement CI pipelines for seamless integration of code changes, automated testing, and deployment of new models.
- Monitoring and Logging: Continuously monitor model performance, data drift, and infrastructure health. Implement comprehensive logging for debugging and auditing.
- Collaboration: Foster collaboration between data scientists, engineers, and product managers through shared platforms and clear communication channels.
- Version Control: Track and manage all artifacts, including code, data, models, and configurations, using version control systems like Git.
- Environment Parity: Use Docker to ensure the development, staging, and production environments are identical. Package your application into one or more Docker images with Docker Compose for seamless distribution and deployment in Swarm mode, if applicable.

## II. AI Product Lifecycle Stages & MLOps Implementation:

## A. Problem Definition & Data Collection:

- Business Understanding: Clearly define the business problem and desired outcomes. Establish measurable success metrics. Define both ML metrics (e.g., F1-score) and Business metrics (e.g., inference latency $<200 \mathrm{~ms}$ )
- Data Identification & Acquisition: Identify and collect relevant data from various sources. Document data sources, formats, and potential biases.
- Data Validation: Implement automated checks for schema consistency and missing values during ingestion.
- Data Exploration & Analysis (EDA): Perform EDA to understand data characteristics, identify patterns, and detect potential issues (e.g., missing values, outliers).
- Security: As per guidelines, all sensitive data must be encrypted at rest and in transit.
- MLOps:
    - Version-control data-collection scripts and configurations.
    - Automate data ingestion and validation processes.
    - Implement data quality checks and monitoring.

## B. Data Preprocessing & Feature Engineering:

- Data Cleaning & Transformation: Clean and transform the data to prepare it for model training. Handle missing values, outliers, and inconsistencies.
- Feature Engineering: Create new features from existing ones to improve model performance.
- Feature Store Concept: Even if a full feature store isn’t used, students should version their feature engineering logic separately from model logic.
- Drift Baselines: During EDA, students must calculate the statistical baseline (mean, variance, distribution) of features to be used later for drift detection.
- MLOps:
    - Automate data preprocessing and feature engineering pipelines.
    - Version control the preprocessing scripts and feature engineering logic.
    - Track feature importance and impact on model performance.
    - Record baseline statistics for later comparison.

## C. Model Development & Training:

- Model Selection: Choose appropriate ML algorithms based on the problem and data characteristics.
- Model Training: Train models using the prepared data. Experiment with different hyperparameters and architectures.
- Model Evaluation: Evaluate model performance using appropriate metrics. Compare different models and select the best one.
- Resource Constraints: Given the “No Cloud” restriction, students must optimize models for local/on-prem hardware (e.g., quantization or pruning)
- MLOps:
    - Automate model training and evaluation processes.
    - Track model versions, hyperparameters, and performance metrics.
    - Implement experiment tracking and management tools (e.g., MLflow).
    - Use containerization (e.g., Docker) for reproducible training environments.

## D. Model Deployment:

- Deployment Strategy: Choose a suitable deployment strategy (e.g., batch, online, edge) based on the application requirements.
- Container Strategy: Use docker-compose to manage a multi-container setup: one for the API (FastAPI/Flask), one for the model server, and one for monitoring.
- Health Checks: Implement / health and / ready endpoints in the model API to facilitate automated orchestration.
- Model Serving: Deploy the trained model to a serving infrastructure.
- MLOps:
    - Automate model deployment using CI/CD pipelines.
    - Implement model serving infrastructure (e.g., TensorFlow Serving, TorchServe, REST APIs).
    - Monitor model performance in production.
    - Implement rollback mechanisms for failed deployments.

## E. Model Monitoring & Maintenance:

- Performance Monitoring: Continuously monitor model performance in production. Track key metrics and identify potential issues.
- The Feedback Loop: Implement a mechanism to $\log$ “ground truth” labels as they become available to calculate real-world performance decay.
- Data Drift Detection: Monitor for changes in the input data distribution that could impact model performance.
- Model Retraining: Retrain models periodically or when performance degrades due to data drift.
- Alerting: Configure Prometheus/Grafana to trigger alerts if error rates exceed 5% or if data drift is detected
- MLOps:
    - Implement automated monitoring and alerting systems.
    - Automate model retraining pipelines.
    - Track data drift and model performance over time.
    - Implement model versioning and management.

## III. Technology Stack Recommendations:

- Version Control: Git LFS, DVC
- Data Engineering: Apache Spark, Apache Airflow, Ray
- Experiment Tracking: MLflow
- Containerization: Docker
- CI/CD: Jenkins, GitLab CI/CD, GitHub Actions, DVC
- Model Serving: TensorFlow Serving, TorchServe, REST APIs
- Model Registry: MLflow model registry
- Monitoring: Prometheus, Grafana
- Cloud Platforms: Not Allowed

## IV. Best Practices:

- Code Quality: Write clean, well-documented, and testable code.
- Testing: Implement unit, integration, and end-to-end tests.
- Security: Implement security measures (encryption) to protect data and models.
- Scalability: Design the system to handle increasing data volumes and traffic.
- Explainability: Consider model explainability techniques to understand model decisions.
- Documentation: Maintain comprehensive documentation for all stages of the ML lifecycle.

## V. Continuous Improvement:

- Regularly review and update the AI application and MLOps processes.
- Stay up to date with the latest advancements in ML and MLOps.
- Encourage a culture of learning and experimentation.

Note: This guideline document provides a framework for building AI applications with MLOps and best practices. The specific implementation details will vary depending on the project requirements and context. It is crucial to adapt and refine these guidelines based on experience and feedback.