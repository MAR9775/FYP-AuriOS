A Final Year Project (FYP) that intelligently installs, configures, and manages AI tools and environments on Windows. AuriOS streamlines the setup process for developers, researchers, and enthusiasts, turning a complex task into a simple, automated workflow.

📖 About The Project
Setting up a complete AI development environment on Windows can be a complex and time-consuming process. It often involves:

Managing multiple Python versions and environments.

Installing specific GPU drivers (like CUDA and cuDNN).

Manually installing and configuring core AI/ML frameworks (TensorFlow, PyTorch, etc.).

Juggling countless dependencies and avoiding conflicts.

AuriOS tackles this problem head-on. It's a smart installer and configurator that automates the entire setup, from driver verification to environment creation. Using an intelligent engine, it detects your system's hardware (especially GPUs) and installs the correct, compatible versions of all necessary software, getting you from a fresh Windows install to a ready-to-code AI environment in minutes.

✨ Key Features
🤖 Smart Hardware Detection: Automatically identifies your CPU and GPU (NVIDIA, AMD, Intel) to determine the best drivers and software versions.

🧩 One-Click AI Toolkit: Install popular AI/ML frameworks with a single command or click.

TensorFlow (with GPU support)

PyTorch (with GPU support)

scikit-learn

Jupyter Notebook / JupyterLab

(Add more tools your project supports)

📦 Automated Environment Management: Creates isolated virtual environments (using venv or conda) for each toolkit, preventing dependency conflicts.

🚀 Driver & SDK Installation: Manages the installation and verification of critical drivers and SDKs like NVIDIA CUDA, cuDNN, and DirectML.

✔️ Configuration Wizard: An interactive wizard (GUI or CLI) that guides users through the setup, asking simple questions about their needs.

🔧 System Check & Validator: A built-in tool to verify that all components are installed correctly and can communicate with the hardware (e.g., "Is PyTorch seeing the GPU?").

🛠️ Built With
This project is built using the following core technologies.

Python - For the core scripting and logic.

PyQt5 / Tkinter - For the (optional) Graphical User Interface (GUI).

PowerShell / Batch - For system-level automation and installation scripts.

YAML - For defining configuration "recipes" and toolsets.
