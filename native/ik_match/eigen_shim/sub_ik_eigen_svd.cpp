// SPDX-License-Identifier: GPL-2.0-or-later
// Calls the same Eigen::JacobiSVD, in the same orientation and with the same
// options, that Blender's IK_QJacobian::Invert uses:
//
//   Eigen::JacobiSVD<MatrixXd> svd(m_jacobian, ComputeThinU | ComputeThinV);
//
// m_jacobian is (3 * ntasks) x ndof. This add-on's native path restricts
// itself to a single position task, so it is 3 x ndof.
#include <Eigen/Core>
#include <Eigen/SVD>
#include <cstddef>

extern "C" void sub_ik_eigen_svd(const double *jacobian_row_major,
                                 std::size_t ndof,
                                 double *u_out, // 3 * 3, row major
                                 double *w_out, // 3
                                 double *v_out) // ndof * 3, row major
{
  Eigen::MatrixXd jacobian(3, (Eigen::Index)ndof);
  for (std::size_t r = 0; r < 3; ++r) {
    for (std::size_t c = 0; c < ndof; ++c) {
      jacobian((Eigen::Index)r, (Eigen::Index)c) = jacobian_row_major[r * ndof + c];
    }
  }
  Eigen::JacobiSVD<Eigen::MatrixXd> svd(jacobian,
                                        Eigen::ComputeThinU | Eigen::ComputeThinV);
  const Eigen::MatrixXd &u = svd.matrixU();        // 3 x 3
  const Eigen::VectorXd &w = svd.singularValues(); // 3, descending
  const Eigen::MatrixXd &v = svd.matrixV();        // ndof x 3
  for (std::size_t r = 0; r < 3; ++r) {
    for (std::size_t c = 0; c < 3; ++c) {
      u_out[r * 3 + c] = u((Eigen::Index)r, (Eigen::Index)c);
    }
    w_out[r] = w((Eigen::Index)r);
  }
  for (std::size_t r = 0; r < ndof; ++r) {
    for (std::size_t c = 0; c < 3; ++c) {
      v_out[r * 3 + c] = v((Eigen::Index)r, (Eigen::Index)c);
    }
  }
}
