from Orange.data import Table
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Input, Output, Msg
from orangecontrib.text import Corpus
from AnyQt.QtWidgets import QWidget
from Orange.widgets.utils.widgetpreview import WidgetPreview
import os
from typing import Optional, Set, List, Tuple, Dict, Any
from Orange.widgets.settings import DomainContextHandler, ContextSetting, Setting
from Orange.data.pandas_compat import table_from_frame
import pandas
import stanza
import stroll.stanza
import re

class MyWidget(OWWidget):
    name = "Digital Story Grammar (DSG) \r\n for Orange3"
    description = "A widget to implement and visualise Digital Story Grammar (DSG).\r\n See https://www.tandfonline.com/doi/full/10.1080/13645579.2020.1723205"
    category=None
    icon = "icons/mywidget.svg"
    priority = 200
    keywords = []
    settingsHandler = DomainContextHandler()
    settings_version = 1
    run_nlp = None

    SRL_FIELDS = [ "sent_id", "head_id", "head", "nsubj", "rel", "Arg0", "Arg1", "Arg2",
                   "ArgM-ADV", "ArgM-CAU", "ArgM-DIS", "ArgM-LOC", "ArgM-MNR", "ArgM-MOD", "ArgM-NEG", "ArgM-REC", "ArgM-TMP", ]

    class Inputs:
        corpus = Input("Corpus", Corpus, default=True)

    class Outputs:
        words = Input("Words", Corpus)
        table = Output("DSG", Table)

    def swap_aux_head(self, sentence_df, child, head, heads_head):
        for i in range(0, len(sentence_df)):
            if sentence_df.at[i, "id"] == head:
                sentence_df.at[i, "head"] = child
            elif sentence_df.at[i, "id"] == child:
                sentence_df.at[i, "head"] = heads_head
            elif sentence_df.at[i, "head"] == head:
                sentence_df.at[i, "head"] = child
        return sentence_df

    def correct_attachments_sentence(self, sentence_df):
        children = {}
        xpos = {}
        upos = {}
        text = {}
        heads = {}
        for i, row in sentence_df.iterrows():
            child = row["id"]
            head = row["head"]
            if head not in children:
                children[head] = []
            children[head].append(child)
            xpos[child] = row["xpos"]
            upos[child] = row["upos"]
            text[child] = row["text"]
            heads[child] = head
        for head in children:
            if head != 0 and not re.search("^WW", xpos[head]):
                for child in children[head]:
                    if re.search("^WW", xpos[child]) and upos[child] == "AUX":
                        sentence_df = self.swap_aux_head(sentence_df, child, head, heads[head])
        return sentence_df

    def correct_attachments_table(self, nlp_table_df):
        sentence_df = pandas.DataFrame([])
        nlp_table_df_out = pandas.DataFrame([])
        last_id = -1
        for i, row in nlp_table_df.iterrows():
            if row["id"] < last_id:
                new_sentence_df = self.correct_attachments_sentence(sentence_df)
                if len(nlp_table_df_out) == 0:
                    nlp_table_df_out = new_sentence_df
                else:
                    nlp_table_df_out = pandas.concat([nlp_table_df_out, new_sentence_df])
                sentence_df = pandas.DataFrame([])
            sentence_df = pandas.concat([sentence_df, pandas.DataFrame([row])], ignore_index=True)
            # sentence_df = sentence_df.append(pandas.DataFrame([row]), ignore_index = True)
            last_id = row["id"]
        if len(sentence_df) > 0:
            new_sentence_df = self.correct_attachments_sentence(sentence_df)
            if len(nlp_table_df_out) == 0:
                nlp_table_df_out = new_sentence_df
            else:
                nlp_table_df_out = pandas.concat([nlp_table_df_out, new_sentence_df])
        return nlp_table_df_out

    def nlp_analysis_to_table(self, nlp_analysis):
        nbr_of_words = 0
        for s in nlp_analysis.sentences:
            for w in s.words:
                print()
                print("word: ", w)
                if nbr_of_words == 0:
                    nlp_table_df = pandas.DataFrame({"id": [w.id], 
                                                "text": [w.text], 
                                                "lemma": [w.lemma],
                                                "upos": [w.upos],
                                                "xpos": [w.xpos],
                                                "feats": [w.feats],
                                                "head": [w.head],
                                                "deprel": [w.deprel],
                                                "deps": [w.deps],
                                                "misc": [w.misc],
                                                "start_char": [w.start_char],
                                                "end_char": [w.end_char],
                                                "parent": [w.parent],
                                                "sent": [w.sent],
                                                "srl": [w.srl],
                                                "frame": [w.frame],
                                                })
                else:
                    nlp_table_df.loc[len(nlp_table_df.index)] = [ w.id, w.text, w.lemma, w.upos, w.xpos, w.feats, 
                                                                w.head, w.deprel, w.deps, w.misc, w.start_char, w.end_char, 
                                                                w.parent, w.sent, w.srl, w.frame, ]
                nbr_of_words += 1
        return nlp_table_df

    def analyze_letter(self, run_nlp, letter_id):
        text = self.read_file(letter_id)
        print()
        print("running nlp...", letter_id)
        nlp_analysis = run_nlp(text)
        print("finished running nlp.")
        print()
        print()
        print("running nlp analysis...", letter_id)
        nlp_table_df = self.nlp_analysis_to_table(nlp_analysis)
        print("finished running nlp analysis.")
        print()
        print("running correct attachments table...", letter_id)
        nlp_table_df = self.correct_attachments_table(nlp_table_df)
        print("finished running correct attachments table.")
        print()
        print("running srl analysis...", letter_id)
        srl_table_df = self.nlp_table_to_srl_table(nlp_table_df)
        print("finished running srl analysis.")
        print()
        return text, nlp_table_df, srl_table_df 

    def nlp_table_to_srl_table(self, nlp_table_df):
        srl_table_df = pandas.DataFrame({ field: [] for field in self.SRL_FIELDS })
        srl_data = {}
        nlp_data = {}
        sentence = {}
        last_id = 0
        sent_id = 1
        for i, row in nlp_table_df.iterrows():
            if row['id'] <= last_id:
                if len(srl_data) > 0:
                    self.add_srl_data_to_srl_table(srl_table_df, srl_data, nlp_data, sentence)
                sent_id += 1
                srl_data = {}
                nlp_data = {}
                sentence = {}
            if row['srl'] != "_":
                if row['head'] not in srl_data:
                    srl_data[row['head']] = { "sent_id": sent_id, "head_id": row["head"] }
                if row['srl'] in srl_data[row['head']]:
                    print(f"duplicate role for {row['srl']} [{i}]: {srl_data[row['head']][row['srl']]} and {row['lemma']}")
                    srl_data[row['head']][row['srl']] += " " + row['lemma']
                else:
                    srl_data[row['head']][row['srl']] = row['lemma']
            if row['frame'] == "rel":
                if row['id'] not in srl_data:
                    srl_data[row['id']] = { "sent_id": sent_id, "head_id": row["id"] }
                if row['frame'] not in srl_data[row['id']]:
                    srl_data[row['id']][row['frame']] = row['lemma']
                else:
                    srl_data[row['id']][row['frame']] += " " + row['lemma']
            if row['deprel'] == "nsubj":
                if row['head'] not in nlp_data:
                    nlp_data[row['head']] = { "sent_id": sent_id, "head_id": row["head"] }
                if 'nsubj' in nlp_data[row['head']]:
                    nlp_data[row['head']]["nsubj"] += " " + row['lemma']
                else:
                    nlp_data[row['head']]["nsubj"] = row['lemma']
            if row['deprel'] == "compound:prt":
                if row['head'] not in nlp_data:
                    nlp_data[row['head']] = { "sent_id": sent_id, "head_id": row["head"] }
                if 'head' in nlp_data[row['head']]:
                    nlp_data[row['head']]["head"] += " " + row['lemma']
                else:
                    nlp_data[row['head']]["head"] = row['lemma']
            last_id = row['id']
            sentence[row['id']] = row['lemma']
        if len(srl_data) > 0:
            self.add_srl_data_to_srl_table(srl_table_df, srl_data, nlp_data, sentence)
        return srl_table_df

    def add_srl_data_to_srl_table(self, srl_table_df, srl_data, nlp_data, sentence):
        print(srl_data)
        for phrase_key in srl_data:
            if 'head' in srl_data[phrase_key]:
                srl_data[phrase_key]["head"] += " " + sentence[phrase_key]
            elif phrase_key > 0:
                srl_data[phrase_key]["head"] = sentence[phrase_key]
            else:
                srl_data[phrase_key]["head"] = "FILLER"
            if phrase_key in nlp_data:
                srl_table_df.loc[len(srl_table_df)] = self.srl_dict_to_srl_list(srl_data[phrase_key], nlp_data[phrase_key])
            else:
                srl_table_df.loc[len(srl_table_df)] = self.srl_dict_to_srl_list(srl_data[phrase_key], {})
    
    def srl_dict_to_srl_list(self, srl_dict, nlp_dict):
        srl_list = len(self.SRL_FIELDS) * [ "" ]
        for i in range(0, len(self.SRL_FIELDS)):
            if self.SRL_FIELDS[i] in srl_dict:
                srl_list[i] = srl_dict[self.SRL_FIELDS[i]]
            if self.SRL_FIELDS[i] in nlp_dict:
                srl_list[i] = nlp_dict[self.SRL_FIELDS[i]]
        return srl_list

    def read_file(self, in_file_id):
        return self.corpus.documents[in_file_id]

    def __init__(self):
        super().__init__() 
        import warnings
        warnings.filterwarnings("ignore", message=r"Passing", category=FutureWarning)

    @Inputs.corpus
    def set_corpus(self, corpus: Optional[Corpus]):
        run_nlp = stanza.Pipeline(lang='nl', processors='tokenize,lemma,pos,depparse,srl')
        all_nlp_data = pandas.DataFrame([])
        all_srl_data = pandas.DataFrame([])
        
        # reset gui
        # for i in reversed(range(self.controlArea.layout().count())): 
        #     self.controlArea.layout().itemAt(i).widget().setParent(None)

        if hasattr(self, "corpus"):
            if self.corpus is None:
                print("it is none")
            else:
                print("it is not none")
                if (self.corpus is not corpus):
                    print("it is different")
                else:
                    print("it is the same")

        self.corpus = corpus

        if self.corpus is not None:     
            for letter_id in range(0, len(self.corpus.documents)):
                text, nlp_table_df, srl_table_df = self.analyze_letter(run_nlp, letter_id)
                all_srl_data = pandas.concat([all_srl_data, srl_table_df])
                all_nlp_data = pandas.concat([all_nlp_data, nlp_table_df])

        self.Outputs.table.send(table_from_frame(all_srl_data))

        print()
        print()
        print("NLP analysis:")
        print()
        print(all_nlp_data)
        print()
        print()
        print("SRL analysis")
        print()
        print(all_srl_data)

if __name__ == "__main__":
    WidgetPreview(MyWidget).run()
