# GPA-BPR: Leveraging Meta-Path and Co-Attention for Preference Stability in Personalized Outfit Recommendations
This is the repository for paper [Leveraging Meta-Path and Co-Attention for Preference Stability in Personalized Outfit Recommendations](https://not_yet_published).

## Dependencies

The required packages can be installed using the `requirements.txt` file:

```
pip install -r requirements.txt
```

## Project Structure

- `/data`: Contains the dataset files
- `/feat`: Feature-related files
- `/metapath_data`: Contains metapath-related data
- `/experiments`: Experimental data or results
- `GPABPR.py`: The model File.
- `main.py`: The main script for training and evaluation.
- `Metapath_generator.ipynb`: The program for metapath generation.
- `MCRec.py`: The module for metapath and Co-attention.

## Usage

```
python main.py
```
## Dataset

### /data

The dataset is located in the `/data` directory.

- `train.csv`
- `valid.csv`
- `test.csv`

Format: **UserID|TopID|PositiveBottomID|NegativeBottomID`**
 
### /feat

- `smallnwjc2vec`: Word embedding dataset from ‘NINJAL Web Japanese Corpus.
- `textfeatures` : Textual feature embedding.
- `visualfeatures`:  Visual feature embedding.

Download [here](https://drive.google.com/file/d/1xcp1xRdxc5f-Z8LF_PCEGh48L_0Hp4LF).

### /IQON3000

Download [here](https://drive.google.com/open?id=1sTfUoNPid9zG_MgV--lWZTBP1XZpmcK8).

## Metapath Data

Metapath-related data is stored in the `/metapath_data` directory. The `Metapath_generator.ipynb` notebook is used to generate this data.

## Citation

```
```