/*
 * This file is part of sattle.
 *
 * Developed for the LSST Data Management System.
 * This product includes software developed by the LSST Project
 * (https://www.lsst.org).
 * See the COPYRIGHT file at the top-level directory of this distribution
 * for details of code ownership.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <pybind11/pytypes.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>
#include <stdexcept>
#include <string>

#include "norad.h"
#include "observe.h"

#define PI 3.141592653589793238462643383279

namespace py = pybind11;
using namespace std;
using namespace pybind11::literals;

struct Inputs {
    double lat = -30.244633333333333, lon = -70.74941666666666, ht_in_meters = 2662.75;
    double jd[2] = {2452623.5, 2452623.6};
    double search_radius = 10.;
    double target_ra = 90., target_dec = 30.;
    double rho_sin_phi;
    double rho_cos_phi;
    int i, header_line_shown = 0;

    // Needed for pybind to correctly bind the jd array
    py::array_t<double> get_jd_array() {
        return py::array_t<double>(2, jd);
    }

    void set_jd_array(const py::array_t<double>& arr) {
        if (arr.size() != 2) {
            throw runtime_error("Array must have exactly 2 elements");
        }
        memcpy(jd, arr.data(), 2 * sizeof(double));
    }
};

struct Outputs{
public:
    double ra[2] = {0, 0}; /* Ra at the beginning of the observation */
    double dec[2] = {0, 0}; /* Dec at the beginning of the observation */

    void set_dec_array(const py::array_t<double>& arr) {
       if (arr.size() != max_size) {
            throw runtime_error("Array must have " + to_string(max_size) + " elements");
        }
        memcpy(dec, arr.data(), arr.size() * sizeof(double));
    }

    py::array_t<double> get_dec_array() {
        int arr_len = end(dec)-begin(dec);
        return py::array_t<double>(arr_len, dec);
    }

    // Needed for pybind to correctly bind ra and dec
    py::array_t<double> get_ra_array() {
        int arr_len = end(ra)-begin(ra);
        return py::array_t<double>(arr_len, ra);
    }

    void set_ra_array(const py::array_t<double>& arr) {
        if (arr.size() != max_size) {
            throw runtime_error("Array must have " + to_string(max_size) + " elements");
        }
        memcpy(ra, arr.data(), arr.size() * sizeof(double));
    }

private:
    int max_size = 2;
};

Outputs DLL_FUNC calc_sat(Inputs inputs, tle_t tle)
{
    Outputs outputs;

        // Run the beginning and end time
    printf( "inputs.target_ra %8.4f\n", inputs.target_ra);
    printf( "inputs.target_dec %8.4f\n", inputs.target_dec);

    inputs.target_ra *= PI / 180.;
    inputs.target_dec *= PI / 180.;
    for (int i = 0; i < 2; ++i) {
        double observer_loc[3];

        // Calculate the observer location on earth?? Don't need the second one
       earth_lat_alt_to_parallax( inputs.lat * PI / 180., inputs.ht_in_meters, &inputs.rho_cos_phi,
                                                                 &inputs.rho_sin_phi);
       observer_cartesian_coords( inputs.jd[i],
                    inputs.lon * PI / 180., inputs.rho_cos_phi, inputs.rho_sin_phi, observer_loc);
       printf( "inputs.target_ra %8.4f\n", inputs.target_ra);
       printf( "inputs.target_dec %8.4f\n", inputs.target_dec);
       printf( "inputs.jd[i] %8.4f\n", inputs.jd[i]);
       printf( "lat in pi %8.4f\n", inputs.lat * PI / 180);
       printf( "ht_in_meters %8.4f\n", inputs.ht_in_meters);
       printf( "observer_loc %8.4f\n", *observer_loc);
       printf( "rho_cos_phi %8.4f\n", inputs.rho_cos_phi);
       printf( "rho_sin_phi %8.4f\n", inputs.rho_sin_phi);

       int is_deep = select_ephemeris( &tle);
       double sat_params[N_SAT_PARAMS], radius, d_ra, d_dec;
       double ra, dec, dist_to_satellite, t_since;
       double pos[3]; /* Satellite position vector */
        t_since = (inputs.jd[i] - tle.epoch) * 1440.;
        printf( "tle epoch %8.4f\n",tle.epoch);
        printf( "inputs jd %8.4f\n",inputs.jd[i]);
        printf( "t_since %8.4f\n",t_since);
        if( is_deep)
           {
           SDP4_init( sat_params, &tle);
           SDP4( t_since, &tle, sat_params, pos, NULL);
           }
        else
           {
           SGP4_init( sat_params, &tle);
           SGP4( t_since, &tle, sat_params, pos, NULL);
           }
        get_satellite_ra_dec_delta( observer_loc, pos,
                                &ra, &dec, &dist_to_satellite);
        epoch_of_date_to_j2000( inputs.jd[i], &ra, &dec);
        d_ra = (ra - inputs.target_ra + PI * 4.);
        printf( "d_ra %8.4f\n",d_ra);
        while( d_ra > PI)
           d_ra -= PI + PI;
        d_dec = dec - inputs.target_dec;
        radius = sqrt( d_ra * d_ra + d_dec * d_dec) * 180. / PI;
        printf( "RA (J2000) dec    Delta Radius   \n");
        inputs.header_line_shown = 1;
        printf( "%8.4f %8.4f %8.1f %5.2f\n",
                     ra * 180. / PI, dec * 180. / PI,
                     dist_to_satellite, radius);


        if( radius < inputs.search_radius)      /* good enough for us! */
        {

            if( !inputs.header_line_shown) {
                printf( "RA (J2000) dec    Delta Radius   \n");
                inputs.header_line_shown = 1;
            }
            /* Put RA into 0 to 2pi range: */
            ra = fmod( ra + PI * 10., PI + PI);
            printf( "%8.4f %8.4f %8.1f %5.2f\n",
                     ra * 180. / PI, dec * 180. / PI,
                     dist_to_satellite, radius);

            outputs.ra[i] = ra * 180. / PI;
            outputs.dec[i] = dec * 180. / PI;

            }
        }

    return outputs;
}


PYBIND11_MODULE(sattle, m) {

   py::class_<Inputs>(m, "Inputs")
        .def(py::init<>())
        .def_readwrite("lat", &Inputs::lat)
        .def_readwrite("lon", &Inputs::lon)
        .def_readwrite("ht_in_meters", &Inputs::ht_in_meters)
        .def_property(
           "jd",
           &Inputs::get_jd_array,
           &Inputs::set_jd_array
           )
        .def_readwrite("search_radius", &Inputs::search_radius)
        .def_readwrite("target_ra", &Inputs::target_ra)
        .def_readwrite("target_dec", &Inputs::target_dec)
        .def_readwrite("rho_sin_phi", &Inputs::rho_sin_phi)
        .def_readwrite("rho_cos_phi", &Inputs::rho_cos_phi)
        .def_readwrite("i", &Inputs::i)
        .def_readwrite("header_line_shown", &Inputs::header_line_shown);

    py::class_<tle_t>(m, "TleType")
           .def(py::init<>())
           .def_readwrite("epoch", &tle_t::epoch)
           .def_readwrite("xndt2o", &tle_t::xndt2o)
           .def_readwrite("xndd6o", &tle_t::xndd6o)
           .def_readwrite("bstar", &tle_t::bstar)
           .def_readwrite("xincl", &tle_t::xincl)
           .def_readwrite("xnodeo", &tle_t::xnodeo)
           .def_readwrite("eo", &tle_t::eo)
           .def_readwrite("omegao", &tle_t::omegao)
           .def_readwrite("xmo", &tle_t::xmo)
           .def_readwrite("xno", &tle_t::xno)
           .def_readwrite("norad_number", &tle_t::norad_number)
           .def_readwrite("bulletin_number", &tle_t::bulletin_number)
           .def_readwrite("revolution_number", &tle_t::revolution_number)
           .def_property("classification",
                         [](const tle_t &t) { return string(1, t.classification); },
                         [](tle_t &t, const string &value) { t.classification = value[0]; })
           .def_property("ephemeris_type",
                         [](const tle_t &t) { return string(1, t.ephemeris_type); },
                         [](tle_t &t, const string &value) { t.ephemeris_type = value[0]; })
           .def_property("intl_desig",
                         [](const tle_t &t) { return string(t.intl_desig, 9); },
                         [](tle_t &t, const string &value) {
                             strncpy(t.intl_desig, value.c_str(), 9);
                             t.intl_desig[8] = '\0';
                         });

   py::class_<Outputs>(m, "Outputs")
      .def(py::init<>())  // Default constructor
      .def_property(
      "ra",
      &Outputs::get_ra_array,
      &Outputs::set_ra_array
      )
      .def_property(
      "dec",
      &Outputs::get_dec_array,
      &Outputs::set_dec_array
      )
;


   m.def("calc_sat", &calc_sat);
   m.def("parse_elements", &parse_elements, "line1"_a, "line2"_a, "sat"_a);

}