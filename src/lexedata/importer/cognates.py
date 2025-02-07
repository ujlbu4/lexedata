import re
import typing as t

import pycldf
import openpyxl

from lexedata import cli
from lexedata.types import Language, RowObject, CogSet
import lexedata.util.excel as cell_parsers
from lexedata.importer.excel_matrix import ExcelCognateParser
from lexedata.util.excel import clean_cell_value, get_cell_comment


class CognateEditParser(ExcelCognateParser):
    def language_from_column(self, column: t.List[openpyxl.cell.Cell]) -> Language:
        data = [clean_cell_value(cell) for cell in column[: self.top - 1]]
        # Do we need to know language comments? – comment = get_cell_comment(column[0])
        return Language(
            {
                self.db.dataset["LanguageTable", "name"].name: data[0],
            }
        )

    def properties_from_row(
        self, row: t.List[openpyxl.cell.Cell]
    ) -> t.Optional[RowObject]:
        self.row_prop_separators = [
            self.db.dataset["CognatesetTable", k].separator for k in self.row_header
        ]
        data = [clean_cell_value(cell) for cell in row[: self.left - 1]]
        properties: t.Dict[t.Optional[str], t.Any] = {
            n: (v if sep is None else v.split(sep))
            for n, sep, v in zip(self.row_header, self.row_prop_separators, data)
        }
        if not any(properties.values()):
            return None

        # delete all possible None entries coming from row_header
        cogset: t.Dict[str, t.Any] = {
            key: value for key, value in properties.items() if key is not None
        }

        while None in properties.keys():
            del properties[None]

        comments: t.List[str] = []
        for cell in row[: self.left - 1]:
            c = get_cell_comment(cell)
            if c is not None:
                comments.append(c)
        comment = "\t".join(comments).strip()
        cogset[self.db.dataset["CognatesetTable", "comment"].name] = comment
        return CogSet(cogset)


def header_from_cognate_excel(
    ws: openpyxl.worksheet.worksheet.Worksheet,
    dataset: pycldf.Dataset,
    logger: cli.logging.Logger = cli.logger,
):
    row_header = []
    separators = []
    for (header,) in ws.iter_cols(
        min_row=1,
        max_row=1,
        max_col=len(dataset["CognatesetTable"].tableSchema.columns),
    ):
        column_name = header.value
        if column_name is None:
            column_name = dataset["CognatesetTable", "id"].name
        elif column_name == "CogSet":
            column_name = dataset["CognatesetTable", "id"].name
        try:
            column_name = dataset["CognatesetTable", column_name].name
        except KeyError:
            break
        row_header.append(column_name)
        separators.append(dataset["CognatesetTable", column_name].separator)
        if column_name == dataset["CognatesetTable", "comment"].name:
            logger.warning(
                "Your cognates table has a separate ‘{header.value}’ column for comments, but `lexedata.importer.cognates` expects to extract comments from the cell comments of the cognateset metadata columns, not from a separate column."
            )
            # TODO: What behaviour will happen? Will comments be merged, or will one of cell comments and comment column be ignored in this case?
    return row_header, separators


def import_cognates_from_excel(
    ws: openpyxl.worksheet.worksheet.Worksheet,
    dataset: pycldf.Dataset,
    extractor: re.Pattern = re.compile("/(?P<ID>[^/]*)/?$"),
    logger: cli.logging.Logger = cli.logger,
) -> None:
    logger.info("Loading sheet…")
    logger.info(
        f"Importing cognate sets from sheet {ws.title}, into {dataset.tablegroup._fname}…"
    )

    row_header, _ = header_from_cognate_excel(ws, dataset, logger=logger)
    excel_parser_cognate = CognateEditParser(
        dataset,
        top=2,
        # When the dataset has cognateset comments, that column is not a header
        # column, so this value is one higher than the actual number of header
        # columns, so actually correct for the 1-based indices. When there is
        # no comment column, we need to compensate for the 1-based Excel
        # indices.
        cellparser=cell_parsers.CellParserHyperlink(dataset, extractor=extractor),
        row_header=row_header,
        check_for_language_match=[dataset["LanguageTable", "name"].name],
        check_for_match=[dataset["FormTable", "id"].name],
        check_for_row_match=[dataset["CognatesetTable", "id"].name],
    )
    excel_parser_cognate.db.cache_dataset()
    excel_parser_cognate.db.drop_from_cache("CognatesetTable")
    excel_parser_cognate.db.drop_from_cache("CognateTable")
    logger.info("Parsing cognate Excel…")
    excel_parser_cognate.parse_cells(ws, status_update=None)
    excel_parser_cognate.db.write_dataset_from_cache(
        ["CognateTable", "CognatesetTable"]
    )


if __name__ == "__main__":
    parser = cli.parser(
        description="Load #cognate and #cognatesets from excel file into CLDF"
    )
    parser.add_argument(
        "cogsets",
        nargs="?",
        default="cognates.xlsx",
        help="Path to an Excel file containing cogsets and cognatejudgements (default: cognates.xlsx). The data will be imported from the *active sheet* (probably the last one you had open in Excel) of that spreadsheet.",
    )
    parser.add_argument(
        "--formid-regex",
        type=str,
        default="/(?P<ID>[^/]*)/?$",
        help="A regular expression whose ID group extracts the forms IDs from the links in the cells. For example, if your Form IDs are anchors in a page, you want '#(?P<ID>[^#]*)$', that is, the longest group of non-# characters at the end of the URL. (Default: '/(?P<ID>[^/]*)/?$', which gives the final component of a path, eg. for forms in Lexibank https://lexibank.clld.org/values/FORM_ID/ or using the exporter's default https://example.org/lexicon/FORM_ID)",
    )

    args = parser.parse_args()
    logger = cli.setup_logging(args)

    ws = openpyxl.load_workbook(args.cogset).active

    import_cognates_from_excel(
        ws,
        pycldf.Dataset.from_metadata(args.metadata),
        extractor=re.compile(args.formid_regex),
        logger=logger,
    )
