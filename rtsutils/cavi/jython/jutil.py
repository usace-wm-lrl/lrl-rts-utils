"""Utilities supporting CAVI tools

Java classes used to render dialogs to the user within the
CAVI environmnet
"""

from collections import namedtuple
from datetime import datetime, timedelta
import os
import tempfile
from rtsutils.usgs import USGS_EXTRACT_CODES

try:
    from hec.lang import TimeStep
    from hec.io import TimeSeriesContainer
    from hec.hecmath import TimeSeriesMath
    from hec.hecmath.functions import TimeSeriesFunctions
    from hec.heclib.dss import HecDss, HecDSSUtilities
    from hec.heclib.util import HecTime
except ImportError as ex:
    print(ex)

from java.io import File
from javax.swing import JFileChooser
from javax.swing.filechooser import FileNameExtensionFilter


def put_timeseries(site, dsspath, apart, bpart):
    """Save timeseries to DSS File

    exception handled with a message output saying site not saved, but
    continues on trying additional site/parameter combinations

    Parameters
    ----------
    site: json
        JSON object containing meta data about the site/parameter combination,
        time array and value array
    dsspath: str
        path to dss file
    Returns
    -------
    None

    Raises
    ------
    HEC DSS exception
    """
    site_parameters = namedtuple("site_parameters", site.keys())(**site)
    parameter, unit, data_type, version = USGS_EXTRACT_CODES[site_parameters.code]

    dss = HecDss.open(dsspath)
    try:
        times = [
            HecTime(t, HecTime.MINUTE_GRANULARITY).value() for t in site_parameters.times
        ]

        timestep_min = None
        for t_time in range(len(times) - 1):
            time_step = abs(times[t_time + 1] - times[t_time])
            if time_step < timestep_min or timestep_min is None:
                timestep_min = time_step
        epart = TimeStep().getEPartFromIntervalMinutes(timestep_min)
        # Set the pathname
        if bpart == "Name":
            bpart = site_parameters.name
        elif bpart == "Site Number":
            bpart = site_parameters.site_number

        pathname = "/{0}/{1}/{2}//{3}/{4}/".format(
            apart, bpart, parameter, epart, version
        ).upper()
        # apart, bpart, _, _, _, _ = pathname.split('/')[1:-1]

        container = TimeSeriesContainer()
        container.fullName = pathname
        container.location = apart
        container.parameter = parameter
        container.type = data_type
        container.version = version
        container.interval = timestep_min
        container.units = unit
        container.times = times
        container.values = site_parameters.values
        container.numberValues = len(site_parameters.times)
        container.startTime = times[0]
        container.endTime = times[-1]
        container.timeZoneID = "UTC"
        # container.makeAscending()
        if not TimeSeriesMath.checkTimeSeries(container):
            return 'site_parameters: "{}" not saved to DSS'.format(
                site_parameters.site_number
            )
        tsc = TimeSeriesFunctions.snapToRegularInterval(
            container, epart, "0MIN", "0MIN", "0MIN"
        )

        # Put the data to DSS
        dss.put(tsc)
    except Exception as ex:
        print(ex)
        return "site_parameters: '{}' not saved to DSS".format(
            site_parameters.site_number
        )


def convert_dss(dss_src, dss_dst):
    """convert DSS7 from Cumulus to DSS6 on local machine defined by DSS
    destination

    Parameters
    ----------
    dss_src : string
        DSS downloaded file location
    dss_dst : string
        DSS location, user defined
    """
    msg = "Downloaded grid not found"
    if os.path.exists(dss_src):
        try:
            dss7 = HecDSSUtilities()
            dss7.setDSSFileName(dss_src)
            dss6_temp = os.path.join(tempfile.gettempdir(), "dss6.dss")
            result = dss7.convertVersion(dss6_temp)
            dss6 = HecDSSUtilities()
            dss6.setDSSFileName(dss6_temp)
            max_retries = 10
            for i in range(max_retries):
                dss6.copyFile(dss_dst)
                copy_success = verify_copy(dss6_temp, dss_dst)
                if copy_success:
                    break
                print("Failed DSS copy attempt {} of {}".format(i + 1, max_retries))
            else:
                raise Exception("Failed to copy downloaded grids to destination DSS file")
        finally:
            dss7.close()
            dss6.close()
            print("Try removing tmp DSS files")
            os.remove(dss_src)
            os.remove(dss6_temp)

        msg = "Converted '{}' to '{}' (int={})".format(dss_src, dss_dst, result)

    print(msg)


def verify_copy(dss_src_path, dss_dst_path):
    """Verifies that all pathnames in the source DSS exist in the destination DSS.

    Parameters
    ----------
    dss_src_path : string
        Path of the source DSS file.
    dss_dst_path : string
        Path of the destination DSS file.

    Returns
    -------
    bool
        True if all source DSS pathnames exist in the destination DSS, false if not.
    """
    dss_src = HecDSSUtilities()
    dss_src.setDSSFileName(dss_src_path)
    src_paths = dss_src.getPathnameList(True)
    src_paths = [src_path.upper() for src_path in src_paths]
    dest_dss = HecDSSUtilities()
    dest_dss.setDSSFileName(dss_dst_path)
    dest_paths = dest_dss.getPathnameList(True)
    dest_paths = [dest_path.upper() for dest_path in dest_paths]

    is_fully_copied = True
    for src_path in src_paths:
        if src_path not in dest_paths:
            print("Could not find path {}".format(src_path))
            is_fully_copied = False
            break
    return is_fully_copied


def get_precip_record_datetimes(pathname):
    """Returns start and end datetimes for a given DSS precip record.

    Parameters
    ----------
    pathname : string
        The DSS pathname for which to determine the time window.

    Returns
    -------
    path_start_dt : datetime
        Start timestamp of the record.
    path_end_dt : datetime
        End timestamp of the record.
    """
    split_path = pathname.split("/")
    d_part = split_path[4]
    e_part = split_path[5]
    if e_part[-4:] == "2400":
        temp_dt = datetime.strptime(e_part, "%d%b%Y:2400")
        temp_dt = temp_dt + timedelta(days=1)
        e_part = temp_dt.strftime("%d%b%Y:0000")
    path_start_dt = datetime.strptime(d_part, "%d%b%Y:%H%M")
    path_end_dt = datetime.strptime(e_part, "%d%b%Y:%H%M")
    return path_start_dt, path_end_dt


def get_existing_precip_data_range(dss_path, b_part, f_part):
    """Determine the existing date range of a precip dataset in a DSS file.

    This method does not account for gaps in the dataset.  It only searches for
    the timestamps of the first and last available records.

    Parameters
    ----------
    dss_path : string
        The DSS file to evaluate.
    b_part : string
        The B-part of the precip pathnames.
    f_part : string
        The F-part of the precip pathnames.

    Returns
    -------
    start_dt : datetime
        Timestamp of the earliest available data.
    end_dt : datetime
        Timestamp of the most recent available data.
    """
    start_dt = None
    end_dt = None
    dss = HecDss.open(dss_path)
    try:
        search_str = "B={} F={}".format(b_part, f_part)
        paths = dss.getCatalogedPathnames(search_str)
        for path in paths:
            path_start_dt, path_end_dt = get_precip_record_datetimes(path)
            if not start_dt or path_start_dt < start_dt:
                start_dt = path_start_dt
            if not end_dt or path_end_dt > end_dt:
                end_dt = path_end_dt
    finally:
        dss.done()
    return start_dt, end_dt


class FileChooser(JFileChooser):
    """Java Swing JFileChooser allowing for the user to select the dss file
    for output.  Currently, once seleted the result is written to the user's
    APPDATA to be read later.
    """

    def __init__(self):
        super(FileChooser, self).__init__()
        self.output_path = None
        self.setFileSelectionMode(JFileChooser.FILES_ONLY)
        self.allow = ["dss"]
        self.destpath = None
        self.filetype = None
        self.current_dir = None
        self.title = None
        self.set_dialog_title(self.title)
        self.set_multi_select(False)
        self.set_hidden_files(False)
        self.set_file_type("dss")
        self.set_filter("HEC-DSS File ('*.dss')", "dss")

    def __repr__(self):
        return "{self.__class__.__name__}()".format(self=self)

    def show(self):
        """show the save dialog"""
        return_val = self.showSaveDialog(self)
        if self.destpath is None or self.filetype is None:
            return_val == JFileChooser.CANCEL_OPTION
        if return_val == JFileChooser.APPROVE_OPTION:
            self.approve_option()
        elif return_val == JFileChooser.CANCEL_OPTION:
            self.cancel_option()
        elif return_val == JFileChooser.ERROR_OPTION:
            self.error_option()

    def set_dialog_title(self, title_):
        """Set the dialog title

        Parameters
        ----------
        title_ : string
            title
        """
        self.setDialogTitle(title_)

    def set_current_dir(self, dir_):
        """set directory

        Parameters
        ----------
        dir_ : string
            set dialog current directory
        """
        self.setCurrentDirectory(File(dir_))

    def set_multi_select(self, is_enabled):
        """set multi selection in dialog

        Parameters
        ----------
        is_enabled : bool
            enable dialog multiselection
        """
        self.setMultiSelectionEnabled(is_enabled)

    def set_hidden_files(self, is_enabled):
        """set hidden files

        Parameters
        ----------
        is_enabled : bool
            enable dialog file hiding
        """
        self.setFileHidingEnabled(is_enabled)

    def set_file_type(self, file_type):
        """set dialog file type

        Parameters
        ----------
        file_type : string
            file type
        """
        if file_type.lower() in self.allow:
            self.filetype = file_type.lower()

    def set_filter(self, desc, *ext):
        """set the filter

        Parameters
        ----------
        desc : string
            description
        """
        self.remove_filter(self.getChoosableFileFilters())
        filter_ = FileNameExtensionFilter(desc, ext)
        filter_desc = [d.getDescription() for d in self.getChoosableFileFilters()]
        if not desc in filter_desc:
            self.addChoosableFileFilter(filter_)

    def set_destpath(self, dest_path):
        """set destination path in dialog

        Parameters
        ----------
        dest_path : string
            path to set as destination in dialog
        """
        self.destpath = dest_path

    def remove_filter(self, filter_):
        """remove filter from dialog

        Parameters
        ----------
        filter_ : string
            file extensions to filter in dialog
        """
        _ = [self.removeChoosableFileFilter(f) for f in filter_]

    def get_files(self):
        """get selected files

        Returns
        -------
        List
            selected files from dialog
        """
        files = [f for f in self.getSelectedFiles()]
        return files

    def cancel_option(self):
        """cancel option"""
        for _filter in self.getChoosableFileFilters():
            self.removeChoosableFileFilter(_filter)

    # def error_option(self):
    #     """error option not used"""
    #     ...

    def approve_option(self):
        """set output path to selected file"""
        self.output_path = self.getSelectedFile().getPath()
        if not self.output_path.endswith(".dss"):
            self.output_path += ".dss"
